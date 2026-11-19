"""Read locally trained CivicFix text classifier. No online AI service is used.

Only load model files produced by train_ai_classifier.py on your own machine:
joblib files are trusted-code artifacts and are unsafe from unknown sources.
"""
from functools import lru_cache
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent / 'instance' / 'ai_models' / 'complaint_classifier.joblib'


@lru_cache(maxsize=2)
def _open_model(path_string: str, modified_ns: int):
    from joblib import load
    return load(path_string)  # trusted local model only


def predict_complaint(description):
    """Return a prediction or an honest empty/unavailable state."""
    text = (description or '').strip()
    if len(text) < 10:
        return {'state': 'insufficient_text'}
    if not MODEL_PATH.is_file():
        return {'state': 'not_trained'}

    try:
        bundle = _open_model(str(MODEL_PATH), MODEL_PATH.stat().st_mtime_ns)
        pipeline = bundle['pipeline']
        probabilities = pipeline.predict_proba([text])[0]
        classes = pipeline.classes_
        best_index = int(probabilities.argmax())
        meta = bundle['metadata']
        return {
            'state': 'ready',
            'category': str(classes[best_index]),
            'estimated_probability': round(float(probabilities[best_index]) * 100, 1),
            'low_confidence': float(probabilities[best_index]) < 0.50,
            'source': meta['source'],
            'training_count': meta['training_count'],
            'test_count': meta['test_count'],
            'holdout_accuracy': round(100 * meta['holdout_accuracy'], 1),
            'macro_f1': round(100 * meta['macro_f1'], 1),
            'trained_at': meta['trained_at'],
            'is_demo': meta['source'] == 'demo',
        }
    except Exception:
        # A missing dependency, changed scikit-learn version, or damaged file
        # should never crash the citizen/admin Flask app.
        return {'state': 'unavailable'}
