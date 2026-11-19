document.addEventListener("DOMContentLoaded", function () {
    const accountMenu = document.querySelector(".citizen-account-menu");
    if (!accountMenu) return;

    document.addEventListener("click", function (event) {
        if (accountMenu.open && !accountMenu.contains(event.target)) {
            accountMenu.removeAttribute("open");
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && accountMenu.open) {
            accountMenu.removeAttribute("open");
            const trigger = accountMenu.querySelector(".citizen-account-trigger");
            if (trigger) trigger.focus();
        }
    });
});
