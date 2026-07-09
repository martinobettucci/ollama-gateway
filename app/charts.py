"""Graphiques SVG inline (rendu serveur, sans build front ni CDN) pour le monitoring.

Fonctions pures → chaînes SVG déterministes (testables). Palette **charte P2Enjoy** :
bleu #23468C (primaire) · vert #238C33 (succès) · jaune #D9CF4A (accent) · rouge #F24141 (danger)
· encre #0D0D0D. Chaque graphe porte un `<title>`/`role="img"` accessible et dégrade proprement
(état « aucune donnée ») sans lever.
"""
import math

BRAND = "#23468C"
SUCCESS = "#238C33"
ACCENT = "#D9CF4A"
DANGER = "#F24141"
INK = "#0D0D0D"
MUTED = "#8A94A6"

# Couleurs par classe de statut HTTP (camembert de répartition).
STATUS_COLORS = {"2xx": SUCCESS, "3xx": BRAND, "4xx": ACCENT, "5xx": DANGER}


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _empty(width: int, height: int, label: str) -> str:
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
            f'aria-label="{_esc(label)} — aucune donnée" class="chart-empty">'
            f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle" '
            f'fill="{MUTED}" font-size="13">Aucune donnée</text></svg>')


def hbar(rows: list[tuple[str, float]], title: str = "Barres",
         unit: str = "", color: str = BRAND, width: int = 460) -> str:
    """Barres horizontales : `rows` = [(libellé, valeur)]. Largeur proportionnelle au max."""
    rows = [(str(l), float(v or 0)) for l, v in rows]
    if not rows or max((v for _, v in rows), default=0) <= 0:
        return _empty(width, 120, title)
    row_h, pad_top, label_w, gap = 26, 8, 150, 8
    bar_max = width - label_w - 70
    vmax = max(v for _, v in rows)
    height = pad_top * 2 + row_h * len(rows)
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
             f'aria-label="{_esc(title)}" class="chart">']
    for i, (label, value) in enumerate(rows):
        y = pad_top + i * row_h
        bw = max(2, (value / vmax) * bar_max) if value else 0
        parts.append(
            f'<text x="0" y="{y + 17}" font-size="12.5" fill="{INK}">{_esc(label[:24])}</text>'
            f'<rect x="{label_w}" y="{y + 5}" width="{bw:.1f}" height="{row_h - 12}" '
            f'rx="4" fill="{color}"/>'
            f'<text x="{label_w + bw + gap:.1f}" y="{y + 17}" font-size="12" fill="{MUTED}">'
            f'{_fmt(value)}{_esc(unit)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def donut(parts: list[tuple[str, float, str]], title: str = "Répartition",
          size: int = 180) -> str:
    """Camembert en anneau : `parts` = [(libellé, valeur, couleur)] ; ignore les valeurs nulles."""
    parts = [(l, float(v or 0), c) for l, v, c in parts if (v or 0) > 0]
    total = sum(v for _, v, _ in parts)
    if total <= 0:
        return _empty(size, size, title)
    cx = cy = size / 2
    r, stroke = size / 2 - 6, 22
    rr = r - stroke / 2
    circ = 2 * math.pi * rr
    segs = [f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" '
            f'aria-label="{_esc(title)}" class="chart-donut">']
    offset = 0.0
    for label, value, color in parts:
        frac = value / total
        dash = frac * circ
        segs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{rr:.1f}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-dasharray="{dash:.2f} {circ - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})">'
            f'<title>{_esc(label)} : {_fmt(value)} ({frac * 100:.0f}%)</title></circle>')
        offset += dash
    segs.append(f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="20" '
                f'font-weight="700" fill="{INK}">{_fmt(total)}</text>'
                f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" font-size="11" '
                f'fill="{MUTED}">total</text></svg>')
    return "".join(segs)


def line(points: list[tuple[str, float]], title: str = "Série", color: str = BRAND,
         width: int = 460, height: int = 140) -> str:
    """Courbe (aire) d'une série ordonnée : `points` = [(libellé_x, valeur)]."""
    points = [(str(x), float(v or 0)) for x, v in points]
    if len(points) < 2 or max((v for _, v in points), default=0) <= 0:
        return _empty(width, height, title)
    pad_l, pad_b, pad_t = 8, 20, 10
    vmax = max(v for _, v in points)
    plot_w, plot_h = width - pad_l * 2, height - pad_b - pad_t
    n = len(points)
    xs = [pad_l + (i / (n - 1)) * plot_w for i in range(n)]
    ys = [pad_t + plot_h - (v / vmax) * plot_h for _, v in points]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{pad_t + plot_h:.1f} " + poly + f" {xs[-1]:.1f},{pad_t + plot_h:.1f}"
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}"/>'
                   for x, y in zip(xs, ys))
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
            f'aria-label="{_esc(title)}" class="chart">'
            f'<polygon points="{area}" fill="{color}" opacity="0.10"/>'
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2"/>'
            f'{dots}'
            f'<text x="{pad_l}" y="{height - 5}" font-size="11" fill="{MUTED}">'
            f'{_esc(points[0][0])}</text>'
            f'<text x="{width - pad_l}" y="{height - 5}" font-size="11" fill="{MUTED}" '
            f'text-anchor="end">{_esc(points[-1][0])}</text></svg>')


def _fmt(v: float) -> str:
    """Formatage court (1.2k, 3.4M) pour les étiquettes de valeur."""
    v = float(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}k"
    return str(int(v))
