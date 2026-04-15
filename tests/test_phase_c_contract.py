from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase_c_surface_contract_present():
    landing_html = (ROOT / 'frontend' / 'index.html').read_text()
    app_html = (ROOT / 'frontend' / 'app.html').read_text()
    css = (ROOT / 'frontend' / 'styles.css').read_text()
    js = (ROOT / 'frontend' / 'app.js').read_text()

    # Landing shell moved to index.html
    assert 'landingHeroCanvas' in landing_html

    # Interactive app shell moved to app.html
    assert 'hero-shell' in app_html
    assert 'cortex-3d-block' in app_html
    assert 'bwr-legend-row' in app_html
    assert 'loading-shell' in app_html
    assert 'loadingFactCard' in app_html
    assert 'loadingBrainCanvas' in app_html
    assert 'initHeroStage' in js
    assert '.hero-stage' in css
    assert '.brain-3d-host' in css
