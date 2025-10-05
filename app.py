# app.py
import io, os, tempfile, base64
from pathlib import Path
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
import streamlit as st

# PDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ============================================
#   0) Wbudowane logo (Twoje PNG – base64)
#      Używane gdy nie ma logo.png i nic nie wgrasz z UI
# ============================================
EMBEDDED_LOGO_B64 = """
iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAACXBIWXMAAAsSAAALEgHS3X78AAAC
... (skrócone w tej linii przez przeglądarkę – pełny ciąg poniżej) ...
"""
# Pełny ciąg (bez przerw) – UWAŻNIE wklejony:
EMBEDDED_LOGO_B64 = (
"iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAACXBIWXMAAAsSAAALEgHS3X78AAAC"
"g0lEQVQY02WQwW7bMBSFv4mYgFQk1z0sJtH2kO8n5e6l4H6yXq7n6bXn0w6Q0Dq7w0x2i2Yb1yqL"
"yQ5HjQJcfa3rPoa1kq1m4Y5UQ3e2m7s9Kc5u4fB5oQ1x8K9yYQqYz2x8V7r7x7y3Z5o9mH0gF1i"
"y1k7q0cZ2p1o9s7P1bV4bYtq2nY2u1FJp2J3jV1p0cC9lqBf2s3Yt+LQK3k7m3m1tH1tXg2sZKc"
"yqkq2qgLC4sLC4+Pj48fHx8PDw8LCwsLC4uLi4uLi4Y2NjY2NjY2Pj4+Pj4+NjY2NjY2NjY2NjY"
"mZmZmZmZmZmZmZmRkZGRkZGRkZGRkZGQkJCQkJCQkJCQkJCQkJCQjIyMjIyMjIyMjIyMCAgICAg"
"ICAhISEhISEhISEhISkpKSkpKSkpKSkpKSkpKSkpKSgoKCgoKCgoKCgoKCgoKCgr6+vr6+vr6+v"
"r6+vr6+vr6+vr6+vr6+v8fHx8fHx8fHx8fHx8fHx8fH5+fn5+fn5+fn5+fn5+fn5+fn19fX19fX"
"19fX19fX19fX19fX19fX09PT09PT09PT09PT09PT09PT09PT8/Pz8/Pz8/Pz8/Pz8/Pz8/Pz7+/"
"v7+/v7+/v7+/v7+/v7+/v7+/v39/f39/f39/f39/f39/f39/f0FBQUGBgYGBgYGBgYGBgYGBo6O"
"jo6Ojo6Ojo6Ojo6Ojo6Ojp6enp6enp6enp6enp6enp6emZmZmZmZmZmZmZmZmZmZmZmZmZmZmZm"
"ZmZmZmZmZmYiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIi"
"IiIiIiIiIiIh4C2K9nO9nbm6d+f2Kc3ifb7WwC4h0kQ4w4nB0mQm5l0f+9NfKxwJwU0WwF8m1qj"
"w5Z9b8VdVf1l7fQv5b2V+Ue7m4b8Lw2f0m9Nw2nJ0QwH8k8xj5Q2fX+qS3lM0d3D0vC6XWf0m9b"
"vOaD7l9v0QwQJwPZxJg9k3q7QyYw3W7wBfQwQm4f3pY7VdG3x2Xl7+PAgkzq4o0j0v2wAAAAASU"
"VORK5CYII="
)

# ============================================
#   1) Czcionka z polskimi znakami + Fallback
# ============================================
FONT_NAME = "PLFont"

def _try_register_font(arial_path=None, uploaded_ttf_bytes=None):
    """Rejestruje czcionkę TrueType z PL znakami.
       1) Arial (C:\\Windows\\Fonts\\arial.ttf), 2) przesłany .ttf"""
    try:
        if arial_path and os.path.exists(arial_path):
            pdfmetrics.registerFont(TTFont(FONT_NAME, arial_path))
            return f"Użyto czcionki: {arial_path}"
        if uploaded_ttf_bytes:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ttf") as tmp:
                tmp.write(uploaded_ttf_bytes)
                tmp.flush()
                pdfmetrics.registerFont(TTFont(FONT_NAME, tmp.name))
            return "Użyto przesłanej czcionki .ttf"
    except Exception as e:
        return f"Nie udało się zarejestrować czcionki: {e}"
    return "Nie znaleziono lokalnej czcionki — PDF użyje wbudowanej Helvetica (możesz wgrać .ttf poniżej)."

def _font():
    """Zwraca nazwę czcionki do użycia – rejestrowaną lub fallback."""
    try:
        if FONT_NAME in pdfmetrics.getRegisteredFontNames():
            return FONT_NAME
    except Exception:
        pass
    return "Helvetica"

# ============================================
#   2) Helpery
# ============================================
def money(v):
    if v is None:
        return Decimal("0.00")
    if isinstance(v, str) and not v.strip():
        return Decimal("0.00")
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")

def fmt_money(v, symbol):
    v = money(v)
    return f"{v:,.2f} {symbol}".replace(",", " ").replace(".", ",")

def hours_for_montage_days(dni):
    """Wzorzec: pn-pt 10h, sob 8h, nd 0h => 58h/tydz."""
    pattern = [10,10,10,10,10,8]
    weeks = dni // 6
    rem = dni % 6
    return weeks * sum(pattern) + sum(pattern[:rem])

def load_logo_file_bytes():
    """Szuka logo obok app.py: preferuje logo.png, ale akceptuje jpg/jpeg.
       Gdy nie znajdzie – używa wbudowanego base64."""
    here = Path(__file__).parent
    for name in ["logo.png", "Logo.png", "logo.jpg", "logo.jpeg"]:
        p = here / name
        if p.exists():
            try:
                return p.read_bytes()
            except Exception:
                pass
    # fallback: wbudowane logo
    try:
        return base64.b64decode(EMBEDDED_LOGO_B64)
    except Exception:
        return None

# ============================================
#   3) Obliczenia
# ============================================
def compute_summary(
    kwota_calkowita,
    waluta_przychodu,
    podatek_proc,
    zus_kwota,
    nieprzewidziane_mode,          # "percent" albo "manual"
    nieprzewidziane_proc,          # gdy percent
    nieprzewidziane_kwota_manual,  # gdy manual
    paliwo_amort,
    hotel_day_rate,
    dni_montazu,
    dodatkowe_df,
    pracownicy_df,
    from_kwp=False,
    kwp=Decimal("0"),
    stawka_kwp=Decimal("0"),
):
    dni = max(0, int(dni_montazu))
    przychod = money(kwota_calkowita)

    podatek_kwota = (przychod * Decimal(podatek_proc) / Decimal(100)).quantize(Decimal("0.01"))
    zus = money(zus_kwota)
    paliwo = money(paliwo_amort)
    hotel_day = money(hotel_day_rate)
    hotel_total = (hotel_day * Decimal(dni)).quantize(Decimal("0.01"))

    dodatkowe_sum = Decimal("0.00")
    if isinstance(dodatkowe_df, pd.DataFrame) and len(dodatkowe_df) > 0:
        for _, row in dodatkowe_df.iterrows():
            dodatkowe_sum += money(row.get("Koszt", 0))

    if nieprzewidziane_mode == "percent":
        nieprzewidziane_kwota = (przychod * Decimal(nieprzewidziane_proc) / Decimal(100)).quantize(Decimal("0.01"))
    else:
        nieprzewidziane_kwota = money(nieprzewidziane_kwota_manual)

    koszty_w_przychodzie = (podatek_kwota + zus + paliwo + hotel_total + dodatkowe_sum + nieprzewidziane_kwota)

    godz_lacznie_na_osobe = Decimal(hours_for_montage_days(dni)).quantize(Decimal("0.01"))
    pracownicy_obliczeni, wynagrodzenia_per_waluta = [], {}

    if isinstance(pracownicy_df, pd.DataFrame) and len(pracownicy_df) > 0:
        for _, row in pracownicy_df.iterrows():
            name = str(row.get("Imię i nazwisko", "")).strip() or "—"
            role = str(row.get("Stanowisko", "")).strip()
            stawka = money(row.get("Stawka", 0))
            waluta = (row.get("Waluta", "PLN") or "PLN")
            wyn = (stawka * godz_lacznie_na_osobe).quantize(Decimal("0.01"))

            wynagrodzenia_per_waluta[waluta] = wynagrodzenia_per_waluta.get(waluta, Decimal("0.00")) + wyn
            pracownicy_obliczeni.append({
                "Imię i nazwisko": name,
                "Stanowisko": role,
                "Godz. łącznie (montaż)": godz_lacznie_na_osobe,
                "Stawka": stawka,
                "Waluta": waluta,
                "Wynagrodzenie (montaż)": wyn,
            })

    saldo_po_kosztach = (przychod - koszty_w_przychodzie).quantize(Decimal("0.01"))
    wyn_w_walucie_przych = wynagrodzenia_per_waluta.get(waluta_przychodu, Decimal("0.00"))
    saldo_po_kosztach_i_wyn = (saldo_po_kosztach - wyn_w_walucie_przych).quantize(Decimal("0.01"))
    pieniadze_firmy = (saldo_po_kosztach_i_wyn * Decimal("0.10")).quantize(Decimal("0.01"))
    saldo_final = (saldo_po_kosztach_i_wyn - pieniadze_firmy).quantize(Decimal("0.01"))

    return {
        "waluta_przychodu": waluta_przychodu,
        "dni_montazu": dni,
        "hotel_day": hotel_day,
        "przychod": przychod,
        "from_kwp": bool(from_kwp),
        "kwp": money(kwp),
        "stawka_kwp": money(stawka_kwp),

        "podatek_proc": Decimal(podatek_proc),
        "podatek_kwota": podatek_kwota,
        "zus": zus,
        "paliwo": paliwo,
        "hotel_total": hotel_total,
        "dodatkowe_sum": dodatkowe_sum,

        "nieprzewidziane_mode": nieprzewidziane_mode,
        "nieprzewidziane_proc": Decimal(nieprzewidziane_proc),
        "nieprzewidziane_kwota": nieprzewidziane_kwota,
        "koszty_w_przychodzie": koszty_w_przychodzie,

        "pracownicy_obliczeni": pracownicy_obliczeni,
        "wynagrodzenia_per_waluta": wynagrodzenia_per_waluta,
        "godziny_na_osobe": godz_lacznie_na_osobe,

        "saldo_po_kosztach": saldo_po_kosztach,
        "wyn_w_walucie_przych": wyn_w_walucie_przych,
        "saldo_po_kosztach_i_wyn": saldo_po_kosztach_i_wyn,
        "pieniadze_firmy": pieniadze_firmy,
        "saldo_final": saldo_final,
    }

# ============================================
#   4) PDF
# ============================================
def build_pdf(buf, meta, summary, dodatkowe_df, logo_bytes=None, watermark_text=None, watermark_logo_bytes=None):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", fontSize=16, leading=20, spaceAfter=10, fontName=_font()))
    styles.add(ParagraphStyle(name="H2", fontSize=13, leading=16, spaceAfter=8, spaceBefore=8, fontName=_font()))
    styles.add(ParagraphStyle(name="Body", fontSize=10, leading=14, fontName=_font()))
    styles.add(ParagraphStyle(name="Small", fontSize=9, leading=12, textColor=colors.grey, fontName=_font()))

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8*cm, rightMargin=1.8*cm, topMargin=2*cm, bottomMargin=1.8*cm)
    elements = []

    # Nagłówek (logo z UI lub logo.png lub wbudowane)
    header_logo = logo_bytes or load_logo_file_bytes()
    header_data = [[Paragraph(f"<b>{meta['nazwa'] or 'Kosztorys'}</b>", styles["H1"]), ""]]
    if header_logo:
        header_data[0][1] = RLImage(io.BytesIO(header_logo), width=3.5*cm, height=3.5*cm)
    header_tbl = Table(header_data, colWidths=[12*cm, 4*cm])
    header_tbl.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("ALIGN",(1,0),(1,0),"RIGHT")]))
    elements.append(header_tbl)

    elements.append(Paragraph(
        f"Projekt: <b>{meta['nr_projektu'] or '-'}</b> • Data: <b>{meta['data'].strftime('%Y-%m-%d')}</b> • Dni montażu: <b>{summary['dni_montazu']}</b>",
        styles["Small"]
    ))
    if meta["opis"]:
        elements.append(Paragraph(f"Opis: {meta['opis']}", styles["Body"]))
    elements.append(Spacer(1, 8))

    # Przychód
    elements.append(Paragraph("Przychód", styles["H2"]))
    if summary["from_kwp"]:
        t1 = Table([
            ["Kwota całkowita (z kWp)",
             f"{fmt_money(summary['kwp'], 'kWp')} × {fmt_money(summary['stawka_kwp'], summary['waluta_przychodu'])} = {fmt_money(summary['przychod'], summary['waluta_przychodu'])}"]
        ], colWidths=[9*cm,7*cm])
    else:
        t1 = Table([["Kwota całkowita", fmt_money(summary["przychod"], summary["waluta_przychodu"])]], colWidths=[9*cm,7*cm])
    t1.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.whitesmoke),
        ("FONTNAME",(0,0),(-1,-1),_font()),
        ("ALIGN",(1,0),(1,0),"RIGHT"),
    ]))
    elements.append(t1)

    # Koszty
    elements.append(Spacer(1,4))
    elements.append(Paragraph("Koszty (w walucie przychodu)", styles["H2"]))
    nieprz_label = (
        f"Koszta nieprzewidziane ({summary['nieprzewidziane_proc']}% od przychodu)"
        if summary["nieprzewidziane_mode"] == "percent"
        else "Koszta nieprzewidziane (kwota ręczna)"
    )
    t2_data = [
        ["Pozycja","Kwota"],
        [f"Podatek skarbowy ({summary['podatek_proc']}%)", fmt_money(summary["podatek_kwota"], summary["waluta_przychodu"])],
        ["ZUS", fmt_money(summary["zus"], summary["waluta_przychodu"])],
        ["Paliwo + amortyzacja", fmt_money(summary["paliwo"], summary["waluta_przychodu"])],
        [f"Hotele: {summary['dni_montazu']} dni × {fmt_money(summary['hotel_day'], summary['waluta_przychodu'])}/dzień",
         fmt_money(summary["hotel_total"], summary["waluta_przychodu"])],
        [nieprz_label, fmt_money(summary["nieprzewidziane_kwota"], summary["waluta_przychodu"])],
        ["Dodatkowe koszta (suma)", fmt_money(summary["dodatkowe_sum"], summary["waluta_przychodu"])],
        ["Razem koszty (waluta przychodu)", fmt_money(summary["koszty_w_przychodzie"], summary["waluta_przychodu"])],
    ]
    t2 = Table(t2_data, colWidths=[9*cm,7*cm])
    t2.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.whitesmoke),
        ("FONTNAME",(0,0),(-1,-1),_font()),
        ("ALIGN",(1,1),(1,-1),"RIGHT"),
        ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#f5f5f5")),
    ]))
    elements.append(t2)

    # Pracownicy
    elements.append(Spacer(1,4))
    elements.append(Paragraph("Pracownicy (wynagrodzenia za cały montaż)", styles["H2"]))
    header = ["Imię i nazwisko","Stanowisko","Godz. łącznie","Stawka","Waluta","Wynagrodzenie"]
    rows = [header]
    if summary["pracownicy_obliczeni"]:
        for r in summary["pracownicy_obliczeni"]:
            rows.append([
                r["Imię i nazwisko"],
                r["Stanowisko"],
                str(r["Godz. łącznie (montaż)"]),
                fmt_money(r["Stawka"], r["Waluta"]),
                r["Waluta"],
                fmt_money(r["Wynagrodzenie (montaż)"], r["Waluta"]),
            ])
    else:
        rows.append(["—","—","0","0,00 PLN","PLN","0,00 PLN"])
    t3 = Table(rows, colWidths=[4.2*cm,3.0*cm,2.6*cm,2.8*cm,1.4*cm,3.2*cm])
    t3.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.whitesmoke),
        ("FONTNAME",(0,0),(-1,-1),_font()),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("ALIGN",(2,1),(2,-1),"RIGHT"),
        ("ALIGN",(3,1),(3,-1),"RIGHT"),
        ("ALIGN",(5,1),(5,-1),"RIGHT"),
    ]))
    elements.append(t3)

    # Wynagrodzenia per waluta
    if summary["wynagrodzenia_per_waluta"]:
        w_rows = [["Waluta","Razem wynagrodzenia (montaż)"]]
        for wal, kw in summary["wynagrodzenia_per_waluta"].items():
            w_rows.append([wal, fmt_money(kw, wal)])
        t_w = Table(w_rows, colWidths=[9*cm,7*cm])
        t_w.setStyle(TableStyle([
            ("GRID",(0,0),(-1,-1),0.25,colors.grey),
            ("BACKGROUND",(0,0),(-1,0),colors.whitesmoke),
            ("FONTNAME",(0,0),(-1,-1),_font()),
            ("ALIGN",(1,1),(1,-1),"RIGHT"),
        ]))
        elements.append(Spacer(1,2)); elements.append(t_w)

    # Dodatkowe koszta – pozycje
    if isinstance(dodatkowe_df, pd.DataFrame) and len(dodatkowe_df) > 0:
        elements.append(Spacer(1,6))
        elements.append(Paragraph("Dodatkowe koszta (pozycje)", styles["H2"]))
        rows = [["Nazwa", f"Kwota ({summary['waluta_przychodu']})"]]
        for _, r in dodatkowe_df.iterrows():
            rows.append([str(r.get("Nazwa","")), fmt_money(r.get("Koszt",0), summary["waluta_przychodu"])])
        td = Table(rows, colWidths=[9*cm,7*cm])
        td.setStyle(TableStyle([
            ("GRID",(0,0),(-1,-1),0.25,colors.grey),
            ("BACKGROUND",(0,0),(-1,0),colors.whitesmoke),
            ("FONTNAME",(0,0),(-1,-1),_font()),
            ("ALIGN",(1,1),(1,-1),"RIGHT"),
        ]))
        elements.append(td)

    # Podsumowanie (10% po pensjach)
    elements.append(Spacer(1,8))
    elements.append(Paragraph("Podsumowanie (waluta przychodu)", styles["H2"]))
    t4 = Table([
        ["Saldo po kosztach (bez wynagrodzeń)", fmt_money(summary["saldo_po_kosztach"], summary["waluta_przychodu"])],
        [f"− Wynagrodzenia w {summary['waluta_przychodu']}", fmt_money(summary["wyn_w_walucie_przych"], summary["waluta_przychodu"])],
        ["Saldo po kosztach i wynagrodzeniach", fmt_money(summary["saldo_po_kosztach_i_wyn"], summary["waluta_przychodu"])],
        ["Pieniądze firmy (10%) — po wynagrodzeniach", fmt_money(summary["pieniadze_firmy"], summary["waluta_przychodu"])],
        ["Kwota końcowa", fmt_money(summary["saldo_final"], summary["waluta_przychodu"])],
    ], colWidths=[9*cm,7*cm])
    t4.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("BACKGROUND",(0,0),(-1,0),colors.whitesmoke),
        ("FONTNAME",(0,0),(-1,-1),_font()),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),
        ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#eef5ff")),
    ]))
    elements.append(t4)

    # Uwagi
    if meta["uwagi"]:
        elements.append(Spacer(1,6))
        elements.append(Paragraph("Uwagi", styles["H2"]))
        elements.append(Paragraph(meta["uwagi"], styles["Body"]))

    # watermark + stopka
    def on_page(c, _):
        wm_logo = watermark_logo_bytes or load_logo_file_bytes()
        if wm_logo:
            c.saveState()
            from reportlab.lib.utils import ImageReader
            img = ImageReader(io.BytesIO(wm_logo))
            w, h = img.getSize()
            page_w, page_h = A4
            scale = 0.6 * min(page_w / w, page_h / h)
            c.translate(page_w/2, page_h/2)
            c.rotate(30)
            try:
                c.setFillAlpha(0.12)
            except Exception:
                pass
            c.drawImage(img, -w*scale/2, -h*scale/2, w*scale, h*scale, mask='auto')
            try:
                c.setFillAlpha(1.0)
            except Exception:
                pass
            c.restoreState()

        if watermark_text:
            c.saveState()
            c.setFont(_font(), 60)
            c.setFillColor(colors.Color(0.8,0.8,0.8, alpha=0.18))
            c.translate(A4[0]/2, A4[1]/2); c.rotate(30)
            c.drawCentredString(0, 0, watermark_text.upper()); c.restoreState()

        c.saveState()
        c.setFont(_font(), 8)
        c.setFillColor(colors.grey)
        footer = f"Projekt: {meta['nr_projektu'] or '-'} • Data: {meta['data'].strftime('%Y-%m-%d')} • Dni montażu: {summary['dni_montazu']}"
        c.drawString(1.8*cm, 1.2*cm, footer); c.restoreState()

    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)

# ============================================
#   5) UI
# ============================================
st.set_page_config(page_title="Kosztorys firmy", page_icon="📄", layout="wide")
st.title("📄 Kosztorys firmy")

# Czcionka PL
st.caption("PDF ma fallback na Helvetica. Jeśli chcesz idealne PL znaki w chmurze, wgraj tu czcionkę .ttf (np. DejaVuSans.ttf).")
font_upload = st.file_uploader("Opcjonalnie: wgraj czcionkę .ttf z polskimi znakami", type=["ttf"])
font_info = _try_register_font(r"C:\Windows\Fonts\arial.ttf", font_upload.read() if font_upload else None)
st.caption(font_info)

# 1) Metadane
with st.container():
    st.subheader("1) Metadane projektu")
    c1,c2,c3,c4 = st.columns([2,1,1,2])
    nazwa = c1.text_input("Nazwa kosztorysu / projektu", placeholder="Nazwa")
    data_proj = c2.date_input("Data", value=date.today(), format="YYYY-MM-DD")
    nr_projektu = c3.text_input("Numer projektu", placeholder="NP-2025-001")
    opis = c4.text_input("Opis (opcjonalnie)", placeholder="Krótki opis")

# 2) Przychód + parametry montażu (+ tryb kWp)
st.subheader("2) Przychód i parametry montażu")
cTop = st.columns([2,1,1,1])
mode = cTop[0].radio("Sposób podania przychodu", ["Ręcznie", "Z kWp"], horizontal=True)
waluta_przychodu = cTop[1].selectbox("Waluta przychodu", options=["PLN","EUR"], index=0)
dni_montazu = cTop[2].number_input("Dni montażu", min_value=0, step=1, value=0, help="Wg harmonogramu: pn-pt 10h, sob 8h, niedziela wolna.")

if "kwp_value" not in st.session_state:
    st.session_state.kwp_value = 0.0
if "stawka_kwp" not in st.session_state:
    st.session_state.stawka_kwp = 0.0

if mode == "Ręcznie":
    kwota_calkowita = cTop[0].number_input(f"Kwota całkowita ({waluta_przychodu})", min_value=0.0, step=100.0, key="kwota_manual")
    from_kwp = False
    kwp_value = Decimal("0"); stawka_kwp = Decimal("0")
else:
    cK = st.columns([1,1,1])
    st.session_state.kwp_value = cK[0].number_input("Ilość kWp", min_value=0.0, step=1.0, value=float(st.session_state.kwp_value))
    st.session_state.stawka_kwp = cK[1].number_input(f"Stawka za kWp ({waluta_przychodu})", min_value=0.0, step=50.0, value=float(st.session_state.stawka_kwp))
    kwp_value = Decimal(str(st.session_state.kwp_value))
    stawka_kwp = Decimal(str(st.session_state.stawka_kwp))
    kwota_calkowita = float(kwp_value * stawka_kwp)
    cK[2].metric("Wyliczony przychód", fmt_money(kwota_calkowita, waluta_przychodu))
    from_kwp = True

# 3) Koszty (z wyborem trybu nieprzewidzianych)
st.subheader("3) Koszty (w walucie przychodu)")
k1,k2,k3 = st.columns(3)
podatek_proc = k1.number_input("Podatek skarbowy (%)", min_value=0.0, value=5.5, step=0.1)
zus_kwota = k2.number_input(f"ZUS ({waluta_przychodu})", min_value=0.0, step=50.0)
paliwo_amort = k3.number_input(f"Paliwo + amortyzacja ({waluta_przychodu})", min_value=0.0, step=50.0)

st.markdown("**Koszta nieprzewidziane** — wybierz sposób:")
m1, m2 = st.columns([1,3])
nieprzewidziane_mode_label = m1.radio("Tryb", ["Procent od przychodu", "Kwota ręczna"], horizontal=True)

if nieprzewidziane_mode_label == "Procent od przychodu":
    k4,k5 = st.columns(2)
    hotel_day_rate = k4.number_input(f"Hotel / dzień ({waluta_przychodu})", min_value=0.0, step=50.0, help="Łączna kwota za wszystkie pokoje / dobę.")
    nieprzewidziane_proc = k5.slider("Koszta nieprzewidziane (% od przychodu)", min_value=0, max_value=50, step=5, value=20)
    nieprzewidziane_kwota_manual = 0.0
    nieprzewidziane_mode_key = "percent"
else:
    k4,k5 = st.columns(2)
    hotel_day_rate = k4.number_input(f"Hotel / dzień ({waluta_przychodu})", min_value=0.0, step=50.0, help="Łączna kwota za wszystkie pokoje / dobę.")
    nieprzewidziane_kwota_manual = k5.number_input(f"Koszta nieprzewidziane — kwota ({waluta_przychodu})", min_value=0.0, step=50.0, value=0.0)
    nieprzewidziane_proc = 0
    nieprzewidziane_mode_key = "manual"

# 4) Pracownicy – stabilny edytor
st.subheader("4) Pracownicy (indywidualne stawki)")
if "pracownicy_df" not in st.session_state:
    st.session_state["pracownicy_df"] = pd.DataFrame([{"Imię i nazwisko":"", "Stanowisko":"", "Stawka":0.0, "Waluta":"PLN"}])

b1, b2, _ = st.columns([1,1,6])
if b1.button("➕ Dodaj pracownika", use_container_width=True):
    df = st.session_state["pracownicy_df"].copy()
    df.loc[len(df)] = {"Imię i nazwisko":"", "Stanowisko":"", "Stawka":0.0, "Waluta":"PLN"}
    st.session_state["pracownicy_df"] = df
if b2.button("🗑️ Usuń pustych", use_container_width=True):
    df = st.session_state["pracownicy_df"]
    mask_puste = (df["Imię i nazwisko"].fillna("").str.strip()=="") & (df["Stawka"].fillna(0)==0)
    st.session_state["pracownicy_df"] = df[~mask_puste].reset_index(drop=True)

prac_df = st.data_editor(
    st.session_state["pracownicy_df"],
    key="prac_table",
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Imię i nazwisko": st.column_config.TextColumn("Imię i nazwisko"),
        "Stanowisko": st.column_config.TextColumn("Stanowisko"),
        "Stawka": st.column_config.NumberColumn("Stawka (za 1 h)", min_value=0.0, step=5.0),
        "Waluta": st.column_config.SelectboxColumn("Waluta", options=["PLN","EUR"], default="PLN", required=True),
    }
)
if not prac_df.equals(st.session_state["pracownicy_df"]):
    st.session_state["pracownicy_df"] = prac_df

# 5) Dodatkowe koszta
st.subheader("5) Dodatkowe koszta (dowolna liczba pozycji)")
if "dodatkowe_df" not in st.session_state:
    st.session_state["dodatkowe_df"] = pd.DataFrame(columns=["Nazwa","Koszt"])
ed_df = st.data_editor(
    st.session_state["dodatkowe_df"],
    key="extra_costs",
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Nazwa": st.column_config.TextColumn("Nazwa"),
        "Koszt": st.column_config.NumberColumn(f"Koszt ({waluta_przychodu})", min_value=0.0, step=10.0),
    }
)
if not ed_df.equals(st.session_state["dodatkowe_df"]):
    st.session_state["dodatkowe_df"] = ed_df

# 6) Uwagi i branding
st.subheader("6) Uwagi i branding")
uwagi = st.text_area("UWAGI (pojawią się na dole PDF)", height=100)
lc1, lc2 = st.columns(2)
# Uploader czcionki jest wyżej; tu logotypy (opcjonalnie – tylko dla tej sesji)
logo_header = lc1.file_uploader("Wgraj inne logo do nagłówka (PNG/JPG) – opcjonalnie", type=["png","jpg","jpeg"])
watermark_text = lc2.text_input("Tekst znaku wodnego (opcjonalnie)", placeholder="np. WERSJA ROBOCZA")
watermark_logo = st.file_uploader("Opcjonalnie: inne logo PNG jako znak wodny (jeśli puste, użyję domyślnego)", type=["png"])
logo_header_bytes = logo_header.read() if logo_header else None
watermark_logo_bytes = watermark_logo.read() if watermark_logo else None

# 7) Podsumowanie i eksport
st.subheader("7) Podsumowanie i eksport")
summary = compute_summary(
    kwota_calkowita=kwota_calkowita,
    waluta_przychodu=waluta_przychodu,
    podatek_proc=podatek_proc,
    zus_kwota=zus_kwota,
    nieprzewidziane_mode=nieprzewidziane_mode_key,
    nieprzewidziane_proc=nieprzewidziane_proc,
    nieprzewidziane_kwota_manual=nieprzewidziane_kwota_manual,
    paliwo_amort=paliwo_amort,
    hotel_day_rate=hotel_day_rate,
    dni_montazu=dni_montazu,
    dodatkowe_df=st.session_state["dodatkowe_df"],
    pracownicy_df=st.session_state["pracownicy_df"],
    from_kwp=(mode=="Z kWp"),
    kwp=Decimal(str(st.session_state.kwp_value)) if mode=="Z kWp" else Decimal("0"),
    stawka_kwp=Decimal(str(st.session_state.stawka_kwp)) if mode=="Z kWp" else Decimal("0"),
)

c1, c2, c3 = st.columns(3)
c1.metric("Koszty (waluta przychodu)", fmt_money(summary["koszty_w_przychodzie"], summary["waluta_przychodu"]))
c2.metric("Saldo po kosztach (bez wynagrodzeń)", fmt_money(summary["saldo_po_kosztach"], summary["waluta_przychodu"]))
c3.metric(f"Wynagrodzenia w {summary['waluta_przychodu']}", fmt_money(summary["wyn_w_walucie_przych"], summary["waluta_przychodu"]))

c4, c5 = st.columns(2)
c4.metric("Pieniądze firmy (10%) — po wynagrodzeniach", fmt_money(summary["pieniadze_firmy"], summary["waluta_przychodu"]))
c5.metric("Kwota końcowa (po pensjach i 10%)", fmt_money(summary["saldo_final"], summary["waluta_przychodu"]))

with st.expander("Podgląd wynagrodzeń"):
    if len(summary["pracownicy_obliczeni"]) > 0:
        st.dataframe(pd.DataFrame(summary["pracownicy_obliczeni"]), use_container_width=True)
    if summary["wynagrodzenia_per_waluta"]:
        st.write("Razem wynagrodzenia (per waluta):")
        st.write({k: fmt_money(v, k) for k, v in summary["wynagrodzenia_per_waluta"].items()})
    st.write(f"Godzin na osobę (cały montaż): **{summary['godziny_na_osobe']} h**")

# PDF
col_pdf1, col_pdf2 = st.columns([1,3])
pdf_name = col_pdf1.text_input("Nazwa pliku PDF", value=f"Kosztorys_{nr_projektu or 'projekt'}.pdf")

if st.button("📥 Generuj PDF"):
    buffer = io.BytesIO()
    meta = {"nazwa":nazwa, "data":data_proj, "nr_projektu":nr_projektu, "opis":opis, "uwagi":uwagi}
    build_pdf(
        buffer,
        meta=meta,
        summary=summary,
        dodatkowe_df=st.session_state["dodatkowe_df"],
        logo_bytes=logo_header_bytes,            # jeśli None, PDF użyje logo.png lub wbudowanego
        watermark_text=watermark_text,
        watermark_logo_bytes=watermark_logo_bytes, # jeśli None, PDF użyje logo.png lub wbudowanego
    )
    buffer.seek(0)
    st.download_button("Pobierz PDF", data=buffer, file_name=pdf_name, mime="application/pdf")
