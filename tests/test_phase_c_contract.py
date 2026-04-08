from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase_c_surface_contract_present():
    html = (ROOT / 'frontend' / 'index.html').read_text()
    css = (ROOT / 'frontend' / 'styles.css').read_text()
    js = (ROOT / 'frontend' / 'app.js').read_text()

    assert 'heroCanvas' in html
    assert 'hero-stage' in html
    assert 'heatmap-legend-rail' in html
    assert 'initHeroStage' in js
    assert '.hero-stage' in css
    assert '.page-ambient' in css
