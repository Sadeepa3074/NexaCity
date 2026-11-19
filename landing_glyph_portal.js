/* NexaCity Glyph Portal — progressive enhancement for the landing page.
 * Native browser implementation: no React or third-party dependencies.
 */
(() => {
    "use strict";

    const portal = document.querySelector("[data-glyph-portal]");
    if (!portal) return;

    const stage = portal.querySelector("[data-portal-stage]");
    const svg = portal.querySelector("[data-portal-mask]");
    const maskBase = portal.querySelector("[data-portal-mask-base]");
    const paper = portal.querySelector("[data-portal-paper]");
    const glyph = portal.querySelector("[data-portal-glyph]");
    const reveal = portal.querySelector("[data-portal-reveal]");
    const opening = portal.querySelector("[data-portal-opening]");
    const progressBar = portal.querySelector("[data-portal-progress] span");
    const header = document.querySelector(".landing-header");

    if (!stage || !svg || !maskBase || !paper || !glyph || !reveal || !opening) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduceMotion.matches) return;

    const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
    const smooth = (start, end, value) => {
        const t = clamp((value - start) / (end - start));
        return t * t * (3 - 2 * t);
    };

    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (!context) return;

    let width = 1;
    let height = 1;
    let targetX = 0;
    let targetY = 0;
    let maxScale = 12;
    let raf = 0;
    let isReady = false;
    let headerIsVisible = true;

    // Keep the navigation out of the cinematic opening, then restore it after
    // the portal reveal has completed. The header remains in the document flow.
    const setHeaderVisible = (visible) => {
        if (!header || headerIsVisible === visible) return;
        headerIsVisible = visible;
        header.classList.toggle("is-portal-nav-hidden", !visible);
        header.classList.toggle("is-portal-nav-visible", visible);
        header.inert = !visible;
        if (visible) {
            header.removeAttribute("aria-hidden");
        } else {
            header.setAttribute("aria-hidden", "true");
        }
    };

    const resize = () => {
        const bounds = stage.getBoundingClientRect();
        width = Math.max(1, Math.round(bounds.width));
        height = Math.max(1, Math.round(bounds.height));

        svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
        svg.setAttribute("width", String(width));
        svg.setAttribute("height", String(height));
        maskBase.setAttribute("width", String(width));
        maskBase.setAttribute("height", String(height));
        paper.setAttribute("width", String(width));
        paper.setAttribute("height", String(height));

        const fontSize = Math.max(44, Math.min(width * 0.17, height * 0.27));
        context.font = `800 ${fontSize}px Poppins, Arial, sans-serif`;
        const wordWidth = context.measureText("NEXACITY").width;
        const beforeFocus = context.measureText("NE").width;
        const focusWidth = context.measureText("X").width;
        const left = (width - wordWidth) / 2;
        const baseline = height * 0.535;

        glyph.setAttribute("x", String(width / 2));
        glyph.setAttribute("y", String(baseline));
        glyph.setAttribute("font-size", String(fontSize));
        glyph.setAttribute("letter-spacing", String(-fontSize * 0.055));
        targetX = left + beforeFocus + focusWidth / 2;
        targetY = baseline;
        maxScale = Math.max(10, Math.min(19, Math.max(width, height) / Math.max(1, fontSize * 0.31)));

        const navHeight = header ? Math.ceil(header.getBoundingClientRect().height) : 0;
        portal.style.setProperty("--glyph-header-offset", `${navHeight}px`);
        isReady = true;
        update();
    };

    const update = () => {
        raf = 0;
        if (!isReady) return;

        const sectionBounds = portal.getBoundingClientRect();
        const travel = Math.max(1, portal.offsetHeight - stage.clientHeight);
        const progress = clamp(-sectionBounds.top / travel);
        // Show navigation only once the visitor has fully stepped through the glyph.
        setHeaderVisible(progress >= 0.9);
        const zoomProgress = smooth(0.02, 0.82, progress);
        const scale = 1 + (maxScale - 1) * Math.pow(zoomProgress, 2.05);
        const transform = `translate(${targetX} ${targetY}) scale(${scale}) translate(${-targetX} ${-targetY})`;

        glyph.setAttribute("transform", transform);
        svg.style.opacity = String(1 - smooth(0.86, 1, progress));
        opening.style.opacity = String(1 - smooth(0.035, 0.19, progress));
        opening.style.transform = `translateY(${-12 * smooth(0.035, 0.19, progress)}px)`;
        const revealProgress = smooth(0.35, 0.84, progress);
        reveal.style.opacity = String(revealProgress);
        reveal.style.transform = `translate3d(0, ${22 * (1 - revealProgress)}px, 0)`;
        reveal.style.pointerEvents = revealProgress > 0.72 ? "auto" : "none";
        reveal.inert = revealProgress <= 0.72;
        if (progressBar) progressBar.style.transform = `scaleX(${progress})`;
        portal.dataset.portalProgress = progress.toFixed(3);
    };

    const schedule = () => {
        if (!raf) raf = window.requestAnimationFrame(update);
    };

    // Wait for Poppins when possible, but never hold the landing page hostage to a font request.
    const fontReady = document.fonts && document.fonts.ready
        ? Promise.race([
            document.fonts.ready,
            new Promise((resolve) => window.setTimeout(resolve, 700))
        ])
        : Promise.resolve();

    fontReady.then(() => {
        setHeaderVisible(false);
        portal.classList.add("is-glyph-enhanced");
        resize();
        window.addEventListener("scroll", schedule, { passive: true });
        window.addEventListener("resize", resize, { passive: true });

        if ("ResizeObserver" in window) {
            const observer = new ResizeObserver(resize);
            observer.observe(stage);
            if (header) observer.observe(header);
            portal._glyphPortalObserver = observer;
        }
    });

    // If reduced motion is enabled while the page is open, return to the fully readable static hero.
    const onMotionChange = (event) => {
        if (event.matches) {
            setHeaderVisible(true);
            portal.classList.remove("is-glyph-enhanced");
            svg.style.opacity = "0";
            opening.style.opacity = "0";
            reveal.style.opacity = "1";
            reveal.style.transform = "none";
            reveal.style.pointerEvents = "auto";
            reveal.inert = false;
            if (raf) window.cancelAnimationFrame(raf);
            window.removeEventListener("scroll", schedule);
            window.removeEventListener("resize", resize);
            portal._glyphPortalObserver?.disconnect();
        } else {
            setHeaderVisible(false);
            portal.classList.add("is-glyph-enhanced");
            resize();
            window.addEventListener("scroll", schedule, { passive: true });
            window.addEventListener("resize", resize, { passive: true });
        }
    };

    if (typeof reduceMotion.addEventListener === "function") {
        reduceMotion.addEventListener("change", onMotionChange);
    } else if (typeof reduceMotion.addListener === "function") {
        reduceMotion.addListener(onMotionChange);
    }
})();
