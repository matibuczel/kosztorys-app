# app.py
# ————————————————————————————————————————————————————————————————
# Kosztorys firmy — Streamlit + ReportLab
# Polskie znaki: DejaVuSans (fonts/DejaVuSans.ttf w repo).
# Logo w nagłówku: plik logo.png w repo lub upload w UI.
# Znak wodny: logo (delikatne) + opcjonalny tekst TYLKO jeśli wpiszesz w UI.
# 10% „Pieniądze firmy” liczone PO wynagrodzeniach pracowników.
# ————————————————————————————————————————————————————————————————

import io
import base64
from pathlib import Path
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
import streamlit as st
from PIL import Image  # weryfikacja obrazów

# ReportLab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

# ————————————————————————————————————————————————————————————————
# 0) Awaryjne mini-logo (base64 PNG) gdy brak logo
# ————————————————————————————————————————————————————————————————
EMBEDDED_LOGO_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAACXBIWXMAAA7EAAAOxAGVKw4bAAAA"
    "B3RJTUUH5AkFDxk0c1qZqAAAAKxJREFUOMu1kz0OgkAQhv9J0j0qkI2wQbP0tCk7QdY6mP2kVY7s"
    "mYd0m3kJ2Ykq2wM3m0m6hLk3z3n5E8m3JxGQk9T6z2I3v+gqX0v0d1Q9l1gCz5xq7H0b5w7JQxGJ"
    "kQqU2U5Y9oG1z5bTj1l0C1o0N2V1FQ8bPp6y2R99X7f2b6g8ZC9k0Gm0g0w5nB0lY5Gz0pZ1i7rP"
    "3A4qV9U7iVn5P0cBvB5m0bC6Vv1b2iR8hS2zKpJQ0mXQv4dSq8c5c3wD8B8JzY1E1HcRkQAAAABJ"
    "RU5ErkJggg=="
)

# ————————————————————————————————————————————————————————————————
# 1) Czcionki z PL znakami (DejaVuSans)
# ————————————————————————————————————————————————————————————————
FONT_REGULAR = "PLFont"
FONT_BOLD = "PLFont-Bold"

def register_fonts() -> str:
    """Rejestruje DejaVuSans (regular + opcjonalnie bold). Fallback: Helvetica."""
    here = Path(__file__).parent
    info = []

    def try_register(ttf_path: Path, name: str) -> bool:
        try:
            if ttf_path.exists():
                pdfmetrics.registerFont(TTFont(name, str(ttf_path)))
                return True
        except Exception:
            pass
        return False

    reg_ok = try_register(here / "fonts" / "DejaVuSans.ttf", FONT_REGULAR)
    bold_ok = try_register(here / "fonts" / "DejaVuSans-Bold.ttf", FONT_BOLD)

    if reg_ok:
        info.append("Użyto czcionki: DejaVuSans.ttf")
    else:
        info.append("Brak fonts/DejaVuSans.ttf – użyję awaryjnie Helvetica (bez polskich znaków).")

    if bold_ok:
        info.append("Użyto pogrubienia: DejaVuSans-Bold.ttf")
    else:
        info.append("Brak pogrubienia (opcjonalne): DejaVuSans-Bold.ttf")

    return " • ".join(info)

def font_regular():
    return FONT_REGULAR if FONT_REGULAR in pdfmetrics.getRegisteredFontNames() else "Helvetica"

def font_bold():
    return FONT_BOLD if FONT_BOLD in pdfmetrics.getRegisteredFontNames() else font_regular()

# ————————————————————————————————————————————————————————————————
# 2) Logo/obrazy — sanityzacja i ładowanie
# ————————————————————————————————————————————————————————————————
def sanitize_image_bytes(raw_bytes: bytes) -> bytes | None:
    """Waliduje obraz przez Pillow i zwraca bezpieczny PNG (RGBA)."""
    if not raw_bytes:
        return None
    try:
        im = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return None

def load_local_logo_bytes() -> bytes | None:
    here = Path(__file__).parent
    for name in ["logo.png", "Logo.png", "logo.jpg", "logo.jpeg"]:
        p = here / name
        if p.exists():
            safe = sanitize_image_bytes(p.read_bytes())
            if safe:
                return safe
    return None

def get_header_logo_bytes(user_uploaded: bytes | None) -> bytes | None:
    """Priorytet: upload → plik w repo → wbudowane mini-logo."""
    if user_uploaded:
        safe = sanitize_image_bytes(user_uploaded)
        if safe:
            return safe
    local = load_local_logo_bytes()
    if local:
        return local
    try:
        return sanitize_image_bytes(base64.b64decode(EMBEDDED_LOGO_B64))
    except Exception:
        return None

# ————————————————————————————————————————————————————————————————
# 3) Obliczenia
# ————————————————————————————————————————————————————————————————
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
    s = f"{v:,.2f} {symbol}"
    return s.replace(",", " ").replace(".", ",")

def hours_for_montage_days(dni: int) -> int:
    """6-dniowy tydzień: pn-pt 10h, sob 8h, nd wolna."""
    pattern = [10, 10, 10, 10, 10, 8]
    weeks = dni // 6
    rem = dni % 6
    return weeks * sum(pattern) + sum(pattern[:rem])

def compute_summary(
    kwota_calkowita, waluta_przychodu, podatek_proc, zus_kwota,
    nieprzewidziane_mode, nieprzewidziane_proc, nieprzewidziane_kwota_manual,
    paliwo_amort, hotel_day_rate, dni_montazu, dodatkowe_df, pracownicy_df,
    from_kwp=False, kwp=Decimal("0"), stawka_kwp=Decimal("0"),
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

    koszty_w_przychodzie = podatek_kwota + zus + paliwo + hotel_total + dodatkowe_sum + nieprzewidziane_kwota

    godz_lacznie_na_osobe = Decimal(hours_for_montage_days(dni)).quantize(Decimal("0.01"))
    pracownicy_obliczeni, wynagrodzenia_per_waluta = [], {}

    if isinstance(pracownicy_df, pd.DataFrame) and len(pracownicy_df) > 0:
        for _, row in pracownicy_df.iterrows():
            name = (str(row.get("Imię i nazwisko", "")) or "—").strip() or "—"
            role = str(row.get("Stanowisko", "")).strip()
            stawka = money(row.get("Stawka", 0))
            waluta = (row.get("Waluta", "PLN") or "PLN")
            wyn = (stawka * godz_lacznie_na_osobe).quantize(Decimal("0.01"))
            wynagrodzenia_per_waluta[waluta] = wynagrodzenia_per_waluta.get(waluta, Decimal("0.00")) + wyn
            pracownicy_obliczeni.append({
                "Imię i nazwisko": name, "Stanowisko": role,
                "Godz. łącznie (montaż)": godz_lacznie_na_osobe,
                "Stawka": stawka, "Waluta": waluta,
                "Wynagrodzenie (montaż)": wyn,
            })

    saldo_po_kosztach = (przychod - koszty_w_przychodzie).quantize(Decimal("0.01"))
    wyn_w_walucie_przych = wynagrodzenia_per_waluta.get(waluta_przychodu, Decimal("0.00"))
    saldo_po_kosztach_i_wyn = (saldo_po_kosztach - wyn_w_walucie_przych).quantize(Decimal("0.01"))
    pieniadze_firmy = (saldo_po_kosztach_i_wyn * Decimal("0.10")).quantize(Decimal("0.01"))
    saldo_final = (saldo_po_kosztach_i_wyn - pieniadze_firmy).quantize(Decimal("0.01"))

    return {
        "waluta_przychodu": waluta_przychodu, "dni_montazu": dni, "hotel_day": hotel_day,
        "przychod": przychod, "from_kwp": bool(from_kwp), "kwp": money(kwp), "stawka_kwp": money(stawka_kwp),
        "podatek_proc": Decimal(podatek_proc), "podatek_kwota": podatek_kwota, "zus": zus,
        "paliwo": paliwo, "hotel_total": hotel_total, "dodatkowe_sum": dodatkowe_sum,
        "nieprzewidziane_mode": nieprzewidziane_mode, "nieprzewidziane_proc": Decimal(nieprzewidziane_proc),
        "nieprzewidziane_kwota": nieprzewidziane_kwota, "koszty_w_przychodzie": koszty_w_przychodzie,
        "pracownicy_obliczeni": pracownicy_obliczeni, "wynagrodzenia_per_waluta": wynagrodzenia_per_waluta,
        "godziny_na_osobe": godz_lacznie_na_osobe,
        "saldo_po_kosztach": saldo_po_kosztach, "wyn_w_walucie_przych": wyn_w_walucie_przych,
        "saldo_po_kosztach_i_wyn": saldo_po_kosztach_i_wyn, "pieniadze_firmy": pieniadze_firmy,
        "saldo_final": saldo_final,
    }

# ————————————————————————————————————————————————————————————————
# 4) Generowanie PDF
# ————————————————————————————————————————————————————————————————
def build_pdf(buf, meta, summary, dodatkowe_df, logo_bytes=None, watermark_text=None, watermark_logo_bytes=None):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", fontSize=16, leading=20, spaceAfter=10, fontName=font_bold()))
    styles.add(ParagraphStyle(name="H2", fontSize=13, leading=16, spaceAfter=8, spaceBefore=8, fontName=font_bold()))
    styles.add(ParagraphStyle(name="Body", fontSize=10, leading=14, fontName=font_regular()))
    styles.add(ParagraphStyle(name="Small", fontSize=9, leading=12, textColor=colors.grey, fontName=font_regular()))

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8*cm, rightMargin=1.8*cm, topMargin=2*cm, bottomMargin=1.8*cm)
    elements = []

    # Nagłówek i logo
    header_logo_safe = get_header_logo_bytes(logo_bytes)
    header_data = [[Paragraph(f"<b>{meta['nazwa'] or 'Kosztorys'}</b>", styles["H1"]), ""]]
    if header_logo_safe:
        header_data[0][1] = RLImage(io.BytesIO(header_logo_safe), width=3.2*cm, height=3.2*cm)
    header_tbl = Table(header_data, colWidths=[12*cm, 4*cm])
    header_tbl.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("ALIGN",(1,0),(1,0),"RIGHT")]))
    elements.append(header_tbl)
    elements.append(Paragraph(
        f"Projekt: <b>{meta['nr_projektu'] or '-'}</b> • Data: <b>{meta['data'].strftime('%Y-%m-%d')}</b> • Dni montażu: <b>{summary['dni_montazu']}</b>",
        styles["Small"]
    ))
    if meta["opis"]:
        elements.append(Paragraph(meta["opis"], styles["Body"]))
    elements.append(Spacer(1, 8))

    # PRZYCHÓD
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
        ("FONTNAME",(0,0),(-1,-1),font_regular()),
        ("ALIGN",(1,0),(1,0),"RIGHT"),
    ]))
    elements.append(t1)

    # KOSZTY
    elements.append(Spacer(1,4))
    elements.append(Paragraph("Koszty (w walucie przychodu)", styles["H2"]))
    nieprz_label = (
        f"Koszta nieprzewidziane ({summary['nieprzewidziane_proc']}% od przychodu)"
        if summary["nieprzewidziane_mode"] == "percent" else "Koszta nieprzewidziane (kwota ręczna)"
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
        ("FONTNAME",(0,0),(-1,-1),font_regular()),
        ("ALIGN",(1,1),(1,-1),"RIGHT"),
        ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#f5f5f5")),
    ]))
    elements.append(t2)

    # PRACOWNICY
    elements.append(Spacer(1,4))
    elements.append(Paragraph("Pracownicy (wynagrodzenia za cały montaż)", styles["H2"]))
    header = ["Imię i nazwisko","Stanowisko","Godz. łącznie","Stawka","Waluta","Wynagrodzenie"]
    rows = [header]
    if summary["pracownicy_obliczeni"]:
        for r in summary["pracownicy_obliczeni"]:
            rows.append([
                r["Imię i nazwisko"], r["Stanowisko"],
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
        ("FONTNAME",(0,0),(-1,-1),font_regular()),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("ALIGN",(2,1),(2,-1),"RIGHT"),
        ("ALIGN",(3,1),(3,-1),"RIGHT"),
        ("ALIGN",(5,1),(5,-1),"RIGHT"),
    ]))
    elements.append(t3)

    # Zbiorcze wynagrodzenia per waluta
    if summary["wynagrodzenia_per_waluta"]:
        w_rows = [["Waluta","Razem wynagrodzenia (montaż)"]]
        for wal, kw in summary["wynagrodzenia_per_waluta"].items():
            w_rows.append([wal, fmt_money(kw, wal)])
        t_w = Table(w_rows, colWidths=[9*cm,7*cm])
        t_w.setStyle(TableStyle([
            ("GRID",(0,0),(-1,-1),0.25,colors.grey),
            ("BACKGROUND",(0,0),(-1,0),colors.whitesmoke),
            ("FONTNAME",(0,0),(-1,-1),font_regular()),
            ("ALIGN",(1,1),(1,-1),"RIGHT"),
        ]))
        elements.append(Spacer(1,2)); elements.append(t_w)

    # PODSUMOWANIE
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
        ("FONTNAME",(0,0),(-1,-1),font_regular()),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),
        ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#eef5ff")),
    ]))
    elements.append(t4)

    # UWAGI
    if meta["uwagi"]:
        elements.append(Spacer(1,6))
        elements.append(Paragraph("Uwagi", styles["H2"]))
        elements.append(Paragraph(meta["uwagi"], styles["Body"]))

    # ——— Znak wodny i stopka ———
    def on_page(c, _):
        wm_logo_safe = sanitize_image_bytes(watermark_logo_bytes) if watermark_logo_bytes else header_logo_safe

        # LOGO jako watermark – delikatne i mniejsze
        if wm_logo_safe:
            try:
                img = ImageReader(io.BytesIO(wm_logo_safe))
                w, h = img.getSize()
                page_w, page_h = A4
                scale = 0.6 * min(page_w / w, page_h / h)  # mniej nachalne
                c.saveState()
                c.translate(page_w / 2, page_h / 2)
                c.rotate(30)
                try:
                    c.setFillAlpha(0.12)  # przezroczystość
                except Exception:
                    pass
                c.drawImage(img, -w * scale / 2, -h * scale / 2, w * scale, h * scale, mask='auto')
                try:
                    c.setFillAlpha(1.0)
                except Exception:
                    pass
                c.restoreState()
            except Exception:
                pass

        # Tekst watermarku rysujemy TYLKO jeśli użytkownik wpisał tekst w UI
        if watermark_text and watermark_text.strip():
            txt = watermark_text.strip().upper()
            c.saveState()
            c.setFont(font_bold(), 56)
            c.setFillColor(colors.Color(0.70, 0.70, 0.70, alpha=0.12))
            c.translate(A4[0] / 2, A4[1] / 2)
            c.rotate(30)
            c.drawCentredString(0, 0, txt)
            c.restoreState()

        # Stopka
        c.saveState()
        c.setFont(font_regular(), 8)
        c.setFillColor(colors.grey)
        footer = f"Projekt: {meta['nr_projektu'] or '-'} • Data: {meta['data'].strftime('%Y-%m-%d')} • Dni montażu: {summary['dni_montazu']}"
        c.drawString(1.8 * cm, 1.2 * cm, footer)
        c.restoreState()

    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)

# ————————————————————————————————————————————————————————————————
# 5) UI — Streamlit
# ————————————————————————————————————————————————————————————————
st.set_page_config(page_title="Kosztorys firmy", page_icon="📄", layout="wide")
# ==== TŁO APLIKACJI (tylko w UI, NIE w PDF) ====
import base64  # jeśli już masz import base64 wyżej — ten wiersz pomiń

def _set_bg_gradient():
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(135deg, #f7f9fc 0%, #eef4ff 50%, #f7f9fc 100%) !important;
            background-attachment: fixed;
        }
        /* delikatne "karty" pod treścią */
        .stApp [data-testid="stVerticalBlock"] > div {
            background: rgba(255,255,255,0.65);
            border-radius: 14px;
            padding: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

def _set_bg_image(img_bytes: bytes):
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: url("data:image/png;base64,{b64}") no-repeat center center fixed !important;
            background-size: cover !important;
        }}
        .stApp [data-testid="stVerticalBlock"] > div {{
            background: rgba(255,255,255,0.70);
            border-radius: 14px;
            padding: 12px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

with st.sidebar:
    st.markdown("### 🎨 Tło aplikacji (UI)")
    bg_mode = st.radio("Wybierz tło strony", ["Brak", "Gradient", "Obraz"], horizontal=True)
    bg_file = None
    if bg_mode == "Obraz":
        bg_file = st.file_uploader("Wgraj tło (JPG/PNG)", type=["jpg", "jpeg", "png"], key="bg_upload_ui")

# zastosuj wybrane tło
if bg_mode == "Gradient":
    _set_bg_gradient()
elif bg_mode == "Obraz" and bg_file is not None:
    _set_bg_image(bg_file.read())
# ==== koniec sekcji TŁO ====

st.title("📄 Kosztorys firmy")
st.caption(register_fonts())

# Metadane
st.subheader("1) Metadane projektu")
c1,c2,c3,c4 = st.columns([2,1,1,2])
nazwa = c1.text_input("Nazwa kosztorysu / projektu", placeholder="Nazwa")
data_proj = c2.date_input("Data", value=date.today(), format="YYYY-MM-DD")
nr_projektu = c3.text_input("Numer projektu", placeholder="NP-2025-001")
opis = c4.text_input("Opis (opcjonalnie)", placeholder="Krótki opis")

# Przychód
st.subheader("2) Przychód i parametry montażu")
cTop = st.columns([2,1,1,1])
mode = cTop[0].radio("Sposób podania przychodu", ["Ręcznie", "Z kWp"], horizontal=True)
waluta_przychodu = cTop[1].selectbox("Waluta przychodu", options=["PLN","EUR"], index=0)
dni_montazu = cTop[2].number_input("Dni montażu", min_value=0, step=1, value=0, help="pn-pt 10h, sob 8h, nd wolna")

if "kwp_value" not in st.session_state: st.session_state.kwp_value = 0.0
if "stawka_kwp" not in st.session_state: st.session_state.stawka_kwp = 0.0

if mode == "Ręcznie":
    kwota_calkowita = cTop[0].number_input(f"Kwota całkowita ({waluta_przychodu})", min_value=0.0, step=100.0, key="kwota_manual")
    from_kwp = False; kwp_value = Decimal("0"); stawka_kwp = Decimal("0")
else:
    cK = st.columns([1,1,1])
    st.session_state.kwp_value = cK[0].number_input("Ilość kWp", min_value=0.0, step=1.0, value=float(st.session_state.kwp_value))
    st.session_state.stawka_kwp = cK[1].number_input(f"Stawka za kWp ({waluta_przychodu})", min_value=0.0, step=50.0, value=float(st.session_state.stawka_kwp))
    kwp_value = Decimal(str(st.session_state.kwp_value))
    stawka_kwp = Decimal(str(st.session_state.stawka_kwp))
    kwota_calkowita = float(kwp_value * stawka_kwp)
    cK[2].metric("Wyliczony przychód", fmt_money(kwota_calkowita, waluta_przychodu))
    from_kwp = True

# Koszty
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
    hotel_day_rate = k4.number_input(f"Hotel / dzień ({waluta_przychodu})", min_value=0.0, step=50.0)
    nieprzewidziane_proc = k5.slider("Koszta nieprzewidziane (% od przychodu)", min_value=0, max_value=50, step=5, value=20)
    nieprzewidziane_kwota_manual = 0.0
    nieprzewidziane_mode_key = "percent"
else:
    k4,k5 = st.columns(2)
    hotel_day_rate = k4.number_input(f"Hotel / dzień ({waluta_przychodu})", min_value=0.0, step=50.0)
    nieprzewidziane_kwota_manual = k5.number_input(f"Koszta nieprzewidziane — kwota ({waluta_przychodu})", min_value=0.0, step=50.0, value=0.0)
    nieprzewidziane_proc = 0
    nieprzewidziane_mode_key = "manual"

# Pracownicy
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
    st.session_state["pracownicy_df"], key="prac_table", num_rows="dynamic", use_container_width=True,
    column_config={
        "Imię i nazwisko": st.column_config.TextColumn("Imię i nazwisko"),
        "Stanowisko": st.column_config.TextColumn("Stanowisko"),
        "Stawka": st.column_config.NumberColumn("Stawka (za 1 h)", min_value=0.0, step=5.0),
        "Waluta": st.column_config.SelectboxColumn("Waluta", options=["PLN","EUR"], default="PLN", required=True),
    }
)
if not prac_df.equals(st.session_state["pracownicy_df"]):
    st.session_state["pracownicy_df"] = prac_df

# Dodatkowe koszta
st.subheader("5) Dodatkowe koszta (dowolna liczba pozycji)")
if "dodatkowe_df" not in st.session_state:
    st.session_state["dodatkowe_df"] = pd.DataFrame(columns=["Nazwa","Koszt"])
ed_df = st.data_editor(
    st.session_state["dodatkowe_df"], key="extra_costs", num_rows="dynamic", use_container_width=True,
    column_config={
        "Nazwa": st.column_config.TextColumn("Nazwa"),
        "Koszt": st.column_config.NumberColumn(f"Koszt ({waluta_przychodu})", min_value=0.0, step=10.0)
    }
)
if not ed_df.equals(st.session_state["dodatkowe_df"]):
    st.session_state["dodatkowe_df"] = ed_df

# Uwagi i branding
st.subheader("6) Uwagi i branding")
uwagi = st.text_area("UWAGI (pojawią się na dole PDF)", height=100)
lc1, lc2 = st.columns(2)
logo_header = lc1.file_uploader("Inne logo do nagłówka (opcjonalnie)", type=["png","jpg","jpeg"])
watermark_text = lc2.text_input("Tekst znaku wodnego (opcjonalnie)", placeholder="np. WERSJA ROBOCZA")
watermark_logo = st.file_uploader("Inne logo jako znak wodny (opcjonalnie, PNG/JPG)", type=["png","jpg","jpeg"])
logo_header_bytes = logo_header.read() if logo_header else None
watermark_logo_bytes = watermark_logo.read() if watermark_logo else None

# Podsumowanie + eksport
st.subheader("7) Podsumowanie i eksport")
summary = compute_summary(
    kwota_calkowita=kwota_calkowita, waluta_przychodu=waluta_przychodu,
    podatek_proc=podatek_proc, zus_kwota=zus_kwota,
    nieprzewidziane_mode=nieprzewidziane_mode_key, nieprzewidziane_proc=nieprzewidziane_proc,
    nieprzewidziane_kwota_manual=nieprzewidziane_kwota_manual,
    paliwo_amort=paliwo_amort, hotel_day_rate=hotel_day_rate, dni_montazu=dni_montazu,
    dodatkowe_df=st.session_state["dodatkowe_df"], pracownicy_df=st.session_state["pracownicy_df"],
    from_kwp=(mode=="Z kWp"), kwp=Decimal(str(st.session_state.get("kwp_value",0))),
    stawka_kwp=Decimal(str(st.session_state.get("stawka_kwp",0))),
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
        st.write({k: fmt_money(v, k) for k, v in summary["wynagrodzenia_per_waluta"].items()})
    st.write(f"Godzin na osobę (montaż): **{summary['godziny_na_osobe']} h**")

col_pdf1, col_pdf2 = st.columns([1,3])
pdf_name = col_pdf1.text_input("Nazwa pliku PDF", value=f"Kosztorys_{nr_projektu or 'projekt'}.pdf")

if st.button("📥 Generuj PDF"):
    buffer = io.BytesIO()
    meta = {"nazwa":nazwa, "data":data_proj, "nr_projektu":nr_projektu, "opis":opis, "uwagi":uwagi}
    build_pdf(
        buffer, meta=meta, summary=summary, dodatkowe_df=st.session_state["dodatkowe_df"],
        logo_bytes=logo_header_bytes, watermark_text=watermark_text, watermark_logo_bytes=watermark_logo_bytes,
    )
    buffer.seek(0)
    st.download_button("Pobierz PDF", data=buffer, file_name=pdf_name, mime="application/pdf")
