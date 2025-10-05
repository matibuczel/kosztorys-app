# app.py
from __future__ import annotations

import io
import base64
from datetime import date
from functools import lru_cache

import pandas as pd
import streamlit as st
from PIL import Image

# ===== ReportLab (PDF) =====
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image as RLImage
)
from reportlab.pdfgen.canvas import Canvas


# =========================================================
# 0) USTAWIENIA / POMOCE
# =========================================================

APP_TITLE = "📄 Kosztorys firmy"
FONTS_PATH = "fonts/DejaVuSans.ttf"  # w repo: fonts/DejaVuSans.ttf
WEEK_PATTERN = [10, 10, 10, 10, 10, 8, 0]  # Pn..Nd: 10,10,10,10,10,8,0  -> 58 h/tydz
WEEK_SUM = sum(WEEK_PATTERN)  # 58


def pl_money(x: float) -> str:
    """Format liczby z przecinkiem dziesiętnym (PL)."""
    try:
        s = f"{float(x):,.2f}"
    except Exception:
        s = "0.00"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def read_file_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


@lru_cache(maxsize=1)
def load_local_logo_bytes() -> bytes | None:
    """Logo z repo: logo.png / .jpg."""
    for p in ["logo.png", "logo.jpg", "logo.jpeg", "Logo.png", "Logo.jpg"]:
        b = read_file_bytes(p)
        if b:
            return b
    return None


def sanitize_image_bytes(img_bytes: bytes | None) -> bytes | None:
    """Bezpiecznie konwertuje na PNG (dla PDF i CSS)."""
    if not img_bytes:
        return None
    try:
        im = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def compute_total_hours(days: int) -> int:
    """Liczy łączną liczbę godzin wg wzorca (Pn–Pt 10h, So 8h, Nd 0)."""
    if days <= 0:
        return 0
    full_weeks = days // 7
    rem = days % 7
    return full_weeks * WEEK_SUM + sum(WEEK_PATTERN[:rem])


# =========================================================
# 1) PDF – FONT i STYLE
# =========================================================
def register_fonts() -> str:
    """Rejestruje font DejaVu dla PL znaków."""
    try:
        if not any(f == "DejaVu" for f in pdfmetrics.getRegisteredFontNames()):
            pdfmetrics.registerFont(TTFont("DejaVu", FONTS_PATH))
    except Exception:
        # Jeśli brak pliku – ReportLab użyje bazowych, ale PL znaki mogą nie zadziałać
        pass
    return "DejaVu"


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    font_name = register_fonts() or "Helvetica"
    styles = {
        "H1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontName=font_name, fontSize=16, leading=20
        ),
        "H2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName=font_name, fontSize=12, leading=16
        ),
        "Body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontName=font_name, fontSize=9, leading=12
        ),
        "Small": ParagraphStyle(
            "Small", parent=base["BodyText"], fontName=font_name, fontSize=8, leading=10
        ),
        "Header": ParagraphStyle(
            "Header", parent=base["BodyText"], fontName=font_name, fontSize=10, leading=12
        ),
    }
    return styles


# =========================================================
# 2) PDF – RYSOWANIE ZNAKU WODNEGO I STOPKI
# =========================================================
def make_on_page(wm_logo_bytes: bytes | None, meta: dict, styles: dict):
    """Zwraca funkcję rysującą watermark + nagłówek/stopkę."""
    wm_safe = sanitize_image_bytes(wm_logo_bytes) or sanitize_image_bytes(load_local_logo_bytes())

    def _on_page(c: Canvas, doc):
        # Watermark – tylko obraz (bez tekstu)
        if wm_safe:
            try:
                from reportlab.lib.utils import ImageReader

                img = ImageReader(io.BytesIO(wm_safe))
                w, h = img.getSize()
                page_w, page_h = A4
                # lekko większy znak wodny
                scale = 0.85 * min(page_w / w, page_h / h)
                c.saveState()
                c.translate(page_w / 2, page_h / 2)
                c.rotate(0)
                try:
                    c.setFillAlpha(0.06)  # delikatnie
                except Exception:
                    pass
                c.drawImage(img, -w * scale / 2, -h * scale / 2, w * scale, h * scale, mask="auto")
                try:
                    c.setFillAlpha(1.0)
                except Exception:
                    pass
                c.restoreState()
            except Exception:
                pass

        # Stopka: numer projektu / data / dni
        c.saveState()
        c.setFont(register_fonts() or "Helvetica", 8)
        footer = f"Projekt: {meta.get('nr_projektu') or '-'} • Data: {meta['data'].strftime('%Y-%m-%d')} • Dni montażu: {meta['dni_montazu']}"
        c.drawString(1.8 * cm, 1.2 * cm, footer)
        c.restoreState()

    return _on_page


# =========================================================
# 3) PDF – BUDOWANIE DOKUMENTU
# =========================================================
def build_pdf(
    meta: dict,
    koszty: dict,
    pracownicy_df: pd.DataFrame,
    dodatkowe_df: pd.DataFrame,
    watermark_logo_bytes: bytes | None,
) -> bytes:
    styles = make_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title="Kosztorys",
    )

    elements: list = []

    # --- NAGŁÓWEK z logo w prawym górnym rogu ---
# spróbujmy użyć tego samego logo co watermark, a jeśli brak – weź z repo
header_logo_bytes = watermark_logo_bytes or load_local_logo_bytes()
header_logo_safe = sanitize_image_bytes(header_logo_bytes)

# tytuł po lewej
title_para = Paragraph(f"<b>{meta.get('nazwa') or 'Kosztorys'}</b>", styles["H1"])

# logo po prawej (skalowane do pudełka ~3.2cm × 2.0cm)
if header_logo_safe:
    logo_el = RLImage(io.BytesIO(header_logo_safe))
    logo_el.hAlign = "RIGHT"
    max_w, max_h = 3.2 * cm, 2.0 * cm
    iw, ih = logo_el.imageWidth, logo_el.imageHeight
    scale = min(max_w / iw, max_h / ih)
    logo_el.drawWidth = iw * scale
    logo_el.drawHeight = ih * scale
else:
    logo_el = ""

header_data = [[title_para, logo_el]]
t = Table(header_data, colWidths=[12 * cm, 5 * cm])
t.setStyle(
    TableStyle(
        [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),  # logo do prawej
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
    )
)
elements += [t, Spacer(1, 6)]


    # Dane projektu
    dane_proj = [
        ["Projekt:", meta.get("nazwa") or "-"],
        ["Nr projektu:", meta.get("nr_projektu") or "-"],
        ["Data:", meta["data"].strftime("%Y-%m-%d")],
        ["Dni montażu:", str(meta["dni_montazu"])],
    ]
    tp = Table(dane_proj, colWidths=[4 * cm, 12 * cm])
    tp.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), register_fonts() or "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ]
        )
    )
    elements += [tp, Spacer(1, 10)]

    # Koszty – tabela główna
    elements.append(Paragraph("Koszty (w walucie przychodu)", styles["H2"]))

    koszt_rows = [
        ["Pozycja", "Kwota"],
        [f"Podatek skarbowy (5,5%)", f"{pl_money(koszty['podatek'])} {koszty['waluta']}"],
        ["ZUS", f"{pl_money(koszty['zus'])} {koszty['waluta']}"],
        ["Paliwo + amortyzacja", f"{pl_money(koszty['paliwo'])} {koszty['waluta']}"],
        [
            f"Hotele: {meta['dni_montazu']} dni × {pl_money(koszty['hotel_dzien'])} {koszty['waluta']}/dzień",
            f"{pl_money(koszty['hotele'])} {koszty['waluta']}",
        ],
        [
            f"Koszta nieprzewidziane ({koszty['nieprzewidziane_proc']}% od przychodu)",
            f"{pl_money(koszty['nieprzewidziane_kwota'])} {koszty['waluta']}",
        ],
        [
            "Dodatkowe koszta (suma)",
            f"{pl_money(koszty['dodatkowe_suma'])} {koszty['waluta']}",
        ],
        ["Razem koszty (waluta przychodu)", f"{pl_money(koszty['koszty_razem'])} {koszty['waluta']}"],
    ]
    tk = Table(koszt_rows, colWidths=[12 * cm, 5 * cm])
    tk.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), register_fonts() or "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ]
        )
    )
    elements += [tk, Spacer(1, 12)]

    # Pracownicy
    elements.append(Paragraph("Pracownicy (wynagrodzenia za cały montaż)", styles["H2"]))

    emp_rows = [
        ["Imię i nazwisko", "Stanowisko", "Dni", "Godz. łącznie", "Stawka", "Waluta", "Wynagrodzenie"]
    ]
    for _, r in pracownicy_df.iterrows():
        name = r.get("Imię i nazwisko", "")
        pos = r.get("Stanowisko", "")
        rate = float(r.get("Stawka", 0) or 0)
        wal = r.get("Waluta", "PLN") or "PLN"
        hrs = koszty["godz_lacznie"]
        wyn = rate * hrs
        emp_rows.append(
            [
                name,
                pos,
                str(meta["dni_montazu"]),
                f"{hrs}",
                f"{pl_money(rate)}",
                wal,
                f"{pl_money(wyn)} {wal}",
            ]
        )

    te = Table(emp_rows, colWidths=[5.0 * cm, 3.2 * cm, 1.5 * cm, 2.2 * cm, 2.2 * cm, 1.5 * cm, 1.9 * cm])
    te.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), register_fonts() or "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ]
        )
    )
    elements += [te, Spacer(1, 10)]

    # Dodatkowe koszta – lista
    if not dodatkowe_df.empty:
        elements.append(Paragraph("Dodatkowe koszta (pozycje)", styles["H2"]))
        rows = [["Nazwa", f"Kwota ({koszty['waluta']})"]]
        for _, r in dodatkowe_df.iterrows():
            if (str(r.get("Nazwa", "")).strip()) or float(r.get("Koszt", 0) or 0) > 0:
                rows.append([str(r.get("Nazwa", "")).strip(), pl_money(float(r.get("Koszt", 0) or 0))])

        td = Table(rows, colWidths=[12 * cm, 5 * cm])
        td.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), register_fonts() or "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ]
            )
        )
        elements += [td, Spacer(1, 10)]

    # Podsumowanie
    elements.append(Paragraph("Podsumowanie (waluta przychodu)", styles["H2"]))
    rows_sum = [
        ["Saldo po kosztach (bez wynagrodzeń)", f"{pl_money(koszty['saldo_po_kosztach'])} {koszty['waluta']}"],
        [f"– Wynagrodzenia w PLN", f"{pl_money(koszty['wyn_pln'])} PLN"],
        [f"– Wynagrodzenia w EUR", f"{pl_money(koszty['wyn_eur'])} EUR"],
        ["Pieniądze firmy (10%) — po wynagrodzeniach", f"{pl_money(koszty['pieniadze_firmy'])} {koszty['waluta']}"],
        ["Kwota końcowa", f"{pl_money(koszty['kwota_koncowa'])} {koszty['waluta']}"],
    ]
    ts = Table(rows_sum, colWidths=[12 * cm, 5 * cm])
    ts.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), register_fonts() or "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ]
        )
    )
    elements += [ts, Spacer(1, 10)]

    # Uwagi
    if str(meta.get("uwagi", "")).strip():
        elements.append(Paragraph("Uwagi", styles["H2"]))
        elements.append(Paragraph(str(meta["uwagi"]), styles["Body"]))

    # Build
    on_page = make_on_page(watermark_logo_bytes, meta, styles)
    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)

    return buf.getvalue()


# =========================================================
# 4) UI – TŁO (tylko przeglądarka, NIE PDF)
# =========================================================
def apply_fixed_bg_from_repo_logo():
    logo_bytes = sanitize_image_bytes(load_local_logo_bytes())
    if logo_bytes:
        b64 = base64.b64encode(logo_bytes).decode("utf-8")
        css = f"""
        <style>
        .stApp {{
            background:
                linear-gradient(rgba(255,255,255,0.85), rgba(255,255,255,0.85)),
                url("data:image/png;base64,{b64}") no-repeat center center fixed !important;
            background-size: cover !important;
        }}
        /* delikatne „karty” pod treścią – jasnoszare */
        .stApp [data-testid="stVerticalBlock"] > div {{
            background: rgba(242,244,247,0.85);
            border: 1px solid #e6e8eb;
            border-radius: 14px;
            padding: 14px;
            box-shadow: 0 1px 2px rgba(16,24,40,.04);
        }}
        thead tr {{
            background-color: #f5f6f8 !important;
        }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    else:
        st.markdown(
            """
            <style>
            .stApp {
                background: linear-gradient(135deg, #f7f9fc 0%, #eef4ff 50%, #f7f9fc 100%) !important;
                background-attachment: fixed;
            }
            .stApp [data-testid="stVerticalBlock"] > div {
                background: rgba(242,244,247,0.85);
                border: 1px solid #e6e8eb;
                border-radius: 14px;
                padding: 14px;
                box-shadow: 0 1px 2px rgba(16,24,40,.04);
            }
            </style>
            """,
            unsafe_allow_html=True,
        )


# =========================================================
# 5) UI – STREAMLIT
# =========================================================
st.set_page_config(page_title="Kosztorys firmy", page_icon="📄", layout="wide")
apply_fixed_bg_from_repo_logo()
st.title(APP_TITLE)
st.caption(register_fonts())  # rejestruj font dla PL znaków


# --------- METADANE -----------
st.subheader("1) Metadane projektu")
c1, c2, c3 = st.columns([1.5, 1, 1])
nazwa = c1.text_input("Nazwa kosztorysu / projektu", placeholder="Nazwa")
data_d = c2.date_input("Data", value=date.today(), format="YYYY-MM-DD")
nr_projektu = c3.text_input("Numer projektu", placeholder="NP-2025-001")
uwagi = st.text_area("Uwagi (opcjonalnie)", placeholder="Notatki, ustalenia, itp.")


# --------- PRZYCHÓD -----------
st.subheader("2) Przychód i parametry montażu")
c1, c2, c3 = st.columns([1, 1, 1])
dni_montazu = c1.number_input("Dni montażu", min_value=0, step=1, value=0)
waluta_przychodu = c2.selectbox("Waluta przychodu", options=["PLN", "EUR"], index=0)
sposob = c3.radio("Sposób podania przychodu", ["Ręcznie", "Z mocy (kWp × stawka/kWp)"], horizontal=True)

if sposob == "Ręcznie":
    kwota_calkowita = st.number_input(f"Kwota całkowita ({waluta_przychodu})", min_value=0.0, step=100.0, value=0.0)
else:
    cc1, cc2 = st.columns([1, 1])
    kWp = cc1.number_input("Moc instalacji (kWp)", min_value=0.0, step=0.1, value=0.0)
    stawka_kWp = cc2.number_input(f"Stawka za 1 kWp ({waluta_przychodu})", min_value=0.0, step=100.0, value=0.0)
    kwota_calkowita = kWp * stawka_kWp

st.markdown(f"**Przychód:** {pl_money(kwota_calkowita)} {waluta_przychodu}")


# --------- KOSZTY -----------
st.subheader("3) Koszty w walucie przychodu")

grid1 = st.columns([1, 1, 1])
podatek = 0.055 * kwota_calkowita  # 5.5%
zus = grid1[0].number_input(f"ZUS ({waluta_przychodu})", min_value=0.0, step=50.0, value=0.0)
paliwo = grid1[1].number_input(f"Paliwo + amortyzacja ({waluta_przychodu})", min_value=0.0, step=50.0, value=0.0)

hotel_dzien = grid1[2].number_input(f"Hotel / dzień ({waluta_przychodu})", min_value=0.0, step=10.0, value=0.0)
hotele = hotel_dzien * dni_montazu

g2c1, g2c2 = st.columns([1, 1])
tryb_nieprzew = g2c1.radio("Koszta nieprzewidziane", ["Suwak (% od przychodu)", "Wpiszę ręcznie"], horizontal=True, index=0)
if tryb_nieprzew == "Suwak (% od przychodu)":
    nieprzew_proc = g2c2.slider("Koszta nieprzewidziane (% od przychodu)", min_value=0, max_value=100, step=5, value=20)
    nieprzew_kwota = kwota_calkowita * (nieprzew_proc / 100.0)
else:
    nieprzew_proc = 0
    nieprzew_kwota = g2c2.number_input(f"Koszta nieprzewidziane ({waluta_przychodu})", min_value=0.0, step=50.0, value=0.0)

# ===== 4) PRACOWNICY =====
st.subheader("4) Pracownicy (indywidualne stawki)")

# Inicjalizacja stanu – bez pustego wiersza
if "pracownicy_df" not in st.session_state:
    st.session_state["pracownicy_df"] = pd.DataFrame(
        columns=["row_id", "Imię i nazwisko", "Stanowisko", "Stawka", "Waluta"]
    )

def _add_worker():
    df = st.session_state["pracownicy_df"].copy()
    new_id = int(df["row_id"].max()) + 1 if not df.empty else 1
    new_row = {"row_id": new_id, "Imię i nazwisko": "", "Stanowisko": "", "Stawka": 0.0, "Waluta": "PLN"}
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    st.session_state["pracownicy_df"] = df

def _drop_empty_workers():
    df = st.session_state["pracownicy_df"].copy()
    mask = (df["Imię i nazwisko"].fillna("").str.strip() == "") & (df["Stawka"].fillna(0) == 0)
    st.session_state["pracownicy_df"] = df[~mask].reset_index(drop=True)

pw1, pw2, _ = st.columns([1, 1, 6])
pw1.button("➕ Dodaj pracownika", use_container_width=True, on_click=_add_worker)
pw2.button("🗑️ Usuń pustych", use_container_width=True, on_click=_drop_empty_workers)

prac_df = st.data_editor(
    st.session_state["pracownicy_df"],
    key="workers_editor",
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "row_id": st.column_config.NumberColumn("ID", disabled=True),
        "Imię i nazwisko": st.column_config.TextColumn("Imię i nazwisko"),
        "Stanowisko": st.column_config.TextColumn("Stanowisko"),
        "Stawka": st.column_config.NumberColumn("Stawka (za 1 h)", min_value=0.0, step=5.0),
        "Waluta": st.column_config.SelectboxColumn("Waluta", options=["PLN", "EUR"], default="PLN", required=True),
    },
    column_order=["row_id", "Imię i nazwisko", "Stanowisko", "Stawka", "Waluta"],
)
st.session_state["pracownicy_df"] = prac_df.copy()

# Godziny łącznie wg dni montażu
godz_lacznie = compute_total_hours(int(dni_montazu))

# Sumy wynagrodzeń wg waluty pracownika
wyn_pln = 0.0
wyn_eur = 0.0
if not st.session_state["pracownicy_df"].empty and godz_lacznie > 0:
    for _, r in st.session_state["pracownicy_df"].iterrows():
        rate = float(r.get("Stawka", 0) or 0)
        wal = r.get("Waluta", "PLN") or "PLN"
        wyn = rate * godz_lacznie
        if wal == "PLN":
            wyn_pln += wyn
        else:
            wyn_eur += wyn

# ===== 5) DODATKOWE KOSZTA =====
st.subheader("5) Dodatkowe koszta (dowolna liczba pozycji)")

if "dodatkowe_df" not in st.session_state:
    st.session_state["dodatkowe_df"] = pd.DataFrame(
        columns=["row_id", "Nazwa", "Koszt"]
    )

def _add_extra():
    df = st.session_state["dodatkowe_df"].copy()
    new_id = int(df["row_id"].max()) + 1 if not df.empty else 1
    new_row = {"row_id": new_id, "Nazwa": "", "Koszt": 0.0}
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    st.session_state["dodatkowe_df"] = df

def _drop_empty_extra():
    df = st.session_state["dodatkowe_df"].copy()
    mask = (df["Nazwa"].fillna("").str.strip() == "") & (df["Koszt"].fillna(0) == 0)
    st.session_state["dodatkowe_df"] = df[~mask].reset_index(drop=True)

ex1, ex2, _ = st.columns([1, 1, 6])
ex1.button("➕ Dodaj pozycję", use_container_width=True, on_click=_add_extra)
ex2.button("🗑️ Usuń puste", use_container_width=True, on_click=_drop_empty_extra)

extra_df = st.data_editor(
    st.session_state["dodatkowe_df"],
    key="extras_editor",
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "row_id": st.column_config.NumberColumn("ID", disabled=True),
        "Nazwa": st.column_config.TextColumn("Nazwa"),
        "Koszt": st.column_config.NumberColumn(f"Koszt ({waluta_przychodu})", min_value=0.0, step=10.0),
    },
    column_order=["row_id", "Nazwa", "Koszt"],
)
st.session_state["dodatkowe_df"] = extra_df.copy()

dodatkowe_suma = float(st.session_state["dodatkowe_df"].get("Koszt", pd.Series([])).fillna(0).sum())


# --------- PODSUMOWANIA / KWOTY ----------
koszty_razem = podatek + zus + paliwo + hotele + nieprzew_kwota + dodatkowe_suma
saldo_po_kosztach = kwota_calkowita - koszty_razem  # jeszcze bez wynagrodzeń
pieniadze_firmy = max(saldo_po_kosztach - (wyn_pln if waluta_przychodu == "PLN" else 0) - (wyn_eur if waluta_przychodu == "EUR" else 0), 0.0) * 0.10

# Kwota końcowa po odjęciu wynagrodzeń + 10% firmy (po wynagrodzeniach)
if waluta_przychodu == "PLN":
    kwota_koncowa = saldo_po_kosztach - wyn_pln - pieniadze_firmy
else:
    kwota_koncowa = saldo_po_kosztach - wyn_eur - pieniadze_firmy

# Prezentacja
st.subheader("6) Podsumowanie")
cA, cB = st.columns([1, 1])
with cA:
    st.metric("Koszty łącznie", f"{pl_money(koszty_razem)} {waluta_przychodu}")
    st.metric("Saldo po kosztach (bez wynagrodzeń)", f"{pl_money(saldo_po_kosztach)} {waluta_przychodu}")
with cB:
    st.metric("Wynagrodzenia w PLN", f"{pl_money(wyn_pln)} PLN")
    st.metric("Wynagrodzenia w EUR", f"{pl_money(wyn_eur)} EUR")

st.metric("Pieniądze firmy (10%) — po wynagrodzeniach", f"{pl_money(pieniadze_firmy)} {waluta_przychodu}")
st.metric("Kwota końcowa", f"{pl_money(kwota_koncowa)} {waluta_przychodu}")


# --------- GENEROWANIE PDF ----------
st.subheader("7) Eksport do PDF")

pdf_meta = {
    "nazwa": nazwa,
    "data": data_d,
    "nr_projektu": nr_projektu,
    "dni_montazu": int(dni_montazu),
    "uwagi": uwagi,
}

pdf_koszty = {
    "waluta": waluta_przychodu,
    "podatek": podatek,
    "zus": zus,
    "paliwo": paliwo,
    "hotel_dzien": hotel_dzien,
    "hotele": hotele,
    "nieprzewidziane_proc": nieprzew_proc if tryb_nieprzew == "Suwak (% od przychodu)" else None,
    "nieprzewidziane_kwota": nieprzew_kwota,
    "dodatkowe_suma": dodatkowe_suma,
    "koszty_razem": koszty_razem,
    "saldo_po_kosztach": saldo_po_kosztach,
    "godz_lacznie": godz_lacznie,
    "wyn_pln": wyn_pln,
    "wyn_eur": wyn_eur,
    "pieniadze_firmy": pieniadze_firmy,
    "kwota_koncowa": kwota_koncowa,
}

wm_logo = load_local_logo_bytes()  # watermark w PDF (jeśli brak uploadu, użyje repo logo)

if st.button("🧾 Generuj PDF", use_container_width=True):
    try:
        pdf_bytes = build_pdf(
            meta=pdf_meta,
            koszty=pdf_koszty,
            pracownicy_df=st.session_state["pracownicy_df"].copy(),
            dodatkowe_df=st.session_state["dodatkowe_df"].copy(),
            watermark_logo_bytes=wm_logo,
        )
        st.download_button(
            label="⬇️ Pobierz PDF",
            data=pdf_bytes,
            file_name=f"Kosztorys_{date.today().isoformat()}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
        st.success("PDF wygenerowany.")
    except Exception as e:
        st.error(f"Nie udało się wygenerować PDF: {e}")
