# app.py
from __future__ import annotations

import io
import os
import base64
from datetime import date
from functools import lru_cache
from typing import Dict

import pandas as pd
import streamlit as st
from PIL import Image
from xml.sax.saxutils import escape as xml_escape

# ===== ReportLab =====
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
)
from reportlab.pdfgen.canvas import Canvas


# =============================================================================
# Ustawienia ogólne
# =============================================================================
APP_TITLE = "⚡ Kosztorys firmy"
FONTS_PATH_REG = "fonts/DejaVuSans.ttf"
FONTS_PATH_BOLD = "fonts/DejaVuSans-Bold.ttf"

# Wzór godzin tygodniowych (Pn–So = 10,10,10,10,10,8; Nd=0) → 58h/tydz.
WEEK_PATTERN = [10, 10, 10, 10, 10, 8, 0]
WEEK_SUM = sum(WEEK_PATTERN)  # 58


def fmt2(x) -> str:
    try:
        return f"{float(x):,.2f}".replace(",", " ").replace(".", ",")
    except Exception:
        return str(x)


def register_fonts() -> None:
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", FONTS_PATH_REG))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", FONTS_PATH_BOLD))
    except Exception:
        pass  # awaryjnie wyleci na Helvetica (bez PL znaków)


def make_styles():
    ss = getSampleStyleSheet()

    def s(name, **kw):
        return ParagraphStyle(name, fontName="DejaVuSans", fontSize=10, leading=12, **kw)

    def b(name, **kw):
        return ParagraphStyle(name, fontName="DejaVuSans-Bold", fontSize=10, leading=12, **kw)

    return {
        "Base": s("Base"),
        "H1": ParagraphStyle(
            "H1",
            parent=ss["Heading1"],
            fontName="DejaVuSans-Bold",
            fontSize=16,
            leading=18,
            spaceAfter=6,
        ),
        "Heading2": ParagraphStyle(
            "Heading2",
            parent=ss["Heading2"],
            fontName="DejaVuSans-Bold",
            fontSize=12,
            leading=14,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "TableHeader": b("TableHeader"),
        "Regular": s("Regular"),
        "Small": ParagraphStyle("Small", fontName="DejaVuSans", fontSize=8, leading=10),
    }


def days_to_hours(days: int, hours_per_day: float | None = None) -> float:
    if hours_per_day is not None:
        return float(days) * float(hours_per_day)
    return float(days) * (WEEK_SUM / 6)  # ~9.67h/dzień


@lru_cache(maxsize=1)
def load_local_logo_bytes() -> bytes | None:
    for fname in ("logo.png", "logo.jpg", "logo.jpeg"):
        if os.path.exists(fname):
            with open(fname, "rb") as f:
                return f.read()
    return None


def sanitize_image_bytes(img_bytes: bytes | None) -> bytes | None:
    if not img_bytes:
        return None
    try:
        im = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return img_bytes


def make_on_page(watermark_logo_bytes: bytes | None):
    wm_logo_safe = sanitize_image_bytes(watermark_logo_bytes or load_local_logo_bytes())

    def _on_page(c: Canvas, doc):
        # znak wodny — tylko logo, bez tekstu
        if wm_logo_safe:
            try:
                from reportlab.platypus import Image as RLImage

                img = RLImage(io.BytesIO(wm_logo_safe))
                w, h = img.imageWidth, img.imageHeight
                page_w, page_h = A4
                scale = 0.9 * min(page_w / w, page_h / h)

                c.saveState()
                c.translate(page_w / 2, page_h / 2)
                c.rotate(30)
                try:
                    c.setFillAlpha(0.10)  # delikatnie
                except Exception:
                    pass
                c.drawImage(
                    io.BytesIO(wm_logo_safe),
                    -w * scale / 2,
                    -h * scale / 2,
                    w * scale,
                    h * scale,
                    mask="auto",
                )
                try:
                    c.setFillAlpha(1.0)
                except Exception:
                    pass
                c.restoreState()
            except Exception:
                pass

        # stopka
        c.saveState()
        c.setFont("DejaVuSans", 8)
        meta_txt = getattr(doc, "_footer_meta", "")
        c.drawString(1.6 * cm, 1.2 * cm, meta_txt)
        c.restoreState()

    return _on_page


# =============================================================================
# Budowanie PDF (bez logo w nagłówku – wygląd jak wcześniej)
# =============================================================================
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

    # --- Tytuł (bez HTML, safe) ---
    title_text = xml_escape(str(meta.get("nazwa") or "Kosztorys"))
    elements += [Paragraph(title_text, styles["H1"]), Spacer(1, 6)]

    # --- Dane projektu ---
    dane_proj = [
        ["Projekt", xml_escape(meta.get("nr_projektu") or "—")],
        ["Data", meta.get("data").strftime("%Y-%m-%d") if meta.get("data") else "—"],
        ["Dni montażu", meta.get("dni_montazu") or 0],
    ]
    tab = Table(dane_proj, colWidths=[4 * cm, 13 * cm])
    tab.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.Color(0.85, 0.85, 0.85)),
                ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements += [tab, Spacer(1, 8)]

    # --- Koszty (w walucie przychodu) ---
    elements += [Paragraph("Koszty (w walucie przychodu)", styles["Heading2"])]

    koszty_rows = [
        ["Pozycja", "Kwota"],
        ["Podatek skarbowy (5.5%)", f"{fmt2(koszty['podatek'])} {koszty['waluta_przychodu']}"],
        ["ZUS", f"{fmt2(koszty['zus'])} {koszty['waluta_przychodu']}"],
        ["Paliwo + amortyzacja", f"{fmt2(koszty['paliwo'])} {koszty['waluta_przychodu']}"],
        [
            f"Hotele: {meta.get('dni_montazu',0)} dni × {fmt2(koszty['hotel_dzien'])} {koszty['waluta_przychodu']}/dzień",
            f"{fmt2(koszty['hotele'])} {koszty['waluta_przychodu']}",
        ],
        [
            f"Koszta nieprzewidziane ({int(koszty['nieprzewidziane_proc'])}% od przychodu)",
            f"{fmt2(koszty['nieprzewidziane_kwota'])} {koszty['waluta_przychodu']}",
        ],
        ["Dodatkowe koszta (suma)", f"{fmt2(koszty['dodatkowe_suma'])} {koszty['waluta_przychodu']}"],
        ["Razem koszty (waluta przychodu)", f"{fmt2(koszty['razem_koszty'])} {koszty['waluta_przychodu']}"],
    ]

    koszty_t = Table(koszty_rows, colWidths=[12 * cm, 5 * cm])
    koszty_t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.92, 0.92, 0.92)),
                ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.Color(0.85, 0.85, 0.85)),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements += [koszty_t, Spacer(1, 8)]

    # --- Pracownicy (z sumą per waluta) ---
    elements += [Paragraph("Pracownicy (wynagrodzenia za cały montaż)", styles["Heading2"])]

    pr_df = pracownicy_df.copy()
    for col in ["Dni", "Godz. łącznie", "Stawka"]:
        if col not in pr_df.columns:
            pr_df[col] = 0.0
    if "Wynagrodzenie" not in pr_df.columns:
        pr_df["Wynagrodzenie"] = pr_df["Godz. łącznie"].astype(float) * pr_df["Stawka"].astype(float)

    table_data = [
        ["Imię i nazwisko", "Stanowisko", "Dni", "Godz. łącznie", "Stawka", "Waluta", "Wynagrodzenie"]
    ]
    for _, r in pr_df.iterrows():
        table_data.append(
            [
                xml_escape(str(r.get("Imię i nazwisko", ""))),
                xml_escape(str(r.get("Stanowisko", ""))),
                int(r.get("Dni", 0)),
                fmt2(r.get("Godz. łącznie", 0)),
                fmt2(r.get("Stawka", 0)),
                xml_escape(str(r.get("Waluta", ""))),
                fmt2(r.get("Wynagrodzenie", 0)),
            ]
        )

    sums_by_curr = pr_df.groupby("Waluta", dropna=False)["Wynagrodzenie"].sum().to_dict()
    if sums_by_curr:
        table_data.append(["", "", "", "", "", "", ""])
        for cur, s in sums_by_curr.items():
            table_data.append(["", "", "", "", "", xml_escape(str(cur or "")), fmt2(s)])

    avail = A4[0] - doc.leftMargin - doc.rightMargin
    colWidths = [
        0.30 * avail,  # Imię i nazwisko
        0.20 * avail,  # Stanowisko
        0.07 * avail,  # Dni
        0.12 * avail,  # Godz. łącznie
        0.12 * avail,  # Stawka
        0.07 * avail,  # Waluta
        0.12 * avail,  # Wynagrodzenie
    ]
    prac_t = Table(table_data, colWidths=colWidths, repeatRows=1)
    prac_t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.92, 0.92, 0.92)),
                ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.Color(0.85, 0.85, 0.85)),
                ("ALIGN", (2, 1), (2, -1), "CENTER"),
                ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                ("ALIGN", (4, 1), (4, -1), "RIGHT"),
                ("ALIGN", (5, 1), (5, -1), "CENTER"),
                ("ALIGN", (6, 1), (6, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements += [prac_t, Spacer(1, 8)]

    # --- Dodatkowe koszta ---
    elements += [Paragraph("Dodatkowe koszta (pozycje)", styles["Heading2"])]
    dd_rows = [["Nazwa", f"Kwota ({koszty['waluta_przychodu']})"]]
    for _, r in dodatkowe_df.iterrows():
        kw = float(r.get("Kwota", 0.0))
        if kw:
            dd_rows.append([xml_escape(str(r.get("Nazwa", ""))), fmt2(kw)])
    if len(dd_rows) == 1:
        dd_rows.append(["—", "0,00"])

    dd_t = Table(dd_rows, colWidths=[12 * cm, 5 * cm])
    dd_t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.92, 0.92, 0.92)),
                ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.Color(0.85, 0.85, 0.85)),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements += [dd_t, Spacer(1, 8)]

    # --- Podsumowanie ---
    elements += [Paragraph("Podsumowanie (waluta przychodu)", styles["Heading2"])]
    podsum = [
        ["Saldo po kosztach (bez wynagrodzeń)", f"{fmt2(koszty['saldo_po_kosztach'])} {koszty['waluta_przychodu']}"],
        [
            "– Wynagrodzenia (łącznie, przeliczone do waluty przychodu)",
            f"{fmt2(koszty['wynagrodzenia_w_przychodzie'])} {koszty['waluta_przychodu']}",
        ],
        [f"Pieniądze firmy (10%) — po wynagrodzeniach", f"{fmt2(koszty['pieniadze_firmy'])} {koszty['waluta_przychodu']}"],
        ["Kwota końcowa", f"{fmt2(koszty['kwota_koncowa'])} {koszty['waluta_przychodu']}"],
    ]
    pod_t = Table(podsum, colWidths=[12 * cm, 5 * cm])
    pod_t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.95, 0.95, 0.95)),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.Color(0.85, 0.85, 0.85)),
                ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements += [pod_t]

    # stopka
    doc._footer_meta = f"Projekt: {meta.get('nr_projektu') or '-'} • Data: {meta.get('data').strftime('%Y-%m-%d') if meta.get('data') else '-'} • Dni montażu: {meta.get('dni_montazu') or 0}"

    on_page = make_on_page(watermark_logo_bytes)
    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)

    return buf.getvalue()


# =============================================================================
# UI – Streamlit
# =============================================================================

def _set_bg_with_logo():
    """Bardzo jasne tło (logo) tylko w UI; PDF na to nie patrzy."""
    try:
        b = load_local_logo_bytes()
        if not b:
            return
        encoded = base64.b64encode(b).decode("utf-8")
        st.markdown(
            f"""
            <style>
            /* Delikatny znak wodny w tle UI */
            .stApp::before {{
              content: "";
              position: fixed;
              inset: 0;
              background: url("data:image/png;base64,{encoded}") no-repeat 50% 30% / 55%;
              opacity: .05; /* JAŚNIEJSZE niż wcześniej */
              pointer-events: none;
              z-index: 0;
            }}
            /* odrobinę jaśniejsze kontenery */
            .block-container {{
              z-index: 1;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
    except Exception:
        pass


def _init_state():
    if "employees" not in st.session_state:
        st.session_state.employees = pd.DataFrame(
            [
                {"Imię i nazwisko": "", "Stanowisko": "", "Dni": 0, "Godz. łącznie": 0.0, "Stawka": 0.0, "Waluta": "EUR", "Wynagrodzenie": 0.0}
            ]
        )
    if "extra_costs" not in st.session_state:
        st.session_state.extra_costs = pd.DataFrame([{"Nazwa": "", "Kwota": 0.0}])


def _recalc_employees(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Dni"] = pd.to_numeric(df.get("Dni", 0), errors="coerce").fillna(0).astype(int)
    df["Godz. łącznie"] = pd.to_numeric(df.get("Godz. łącznie", 0.0), errors="coerce").fillna(0.0).astype(float)
    df["Stawka"] = pd.to_numeric(df.get("Stawka", 0.0), errors="coerce").fillna(0.0).astype(float)
    mask = (df["Godz. łącznie"] <= 0.0) & (df["Dni"] > 0)
    df.loc[mask, "Godz. łącznie"] = df.loc[mask, "Dni"].apply(lambda d: days_to_hours(d, None))
    df["Wynagrodzenie"] = df["Godz. łącznie"] * df["Stawka"]
    df["Waluta"] = df.get("Waluta", "EUR").fillna("EUR").astype(str)
    return df


def _extra_costs_sum(df: pd.DataFrame) -> float:
    return pd.to_numeric(df.get("Kwota", 0.0), errors="coerce").fillna(0.0).sum()


def _sum_wages_by_currency(df: pd.DataFrame) -> Dict[str, float]:
    return df.groupby("Waluta", dropna=False)["Wynagrodzenie"].sum().to_dict()


# ----------------------------- UI START -----------------------------
st.set_page_config(page_title=APP_TITLE, page_icon="⚡", layout="wide")
_set_bg_with_logo()
register_fonts()
_init_state()

st.title("Kosztorys firmy")

# Metadane
st.subheader("1) Metadane projektu")
c1, c2, c3 = st.columns((1.3, 1, 0.9))
with c1:
    nazwa = st.text_input("Nazwa kosztorysu / projektu", placeholder="Nazwa")
with c2:
    data_doc = st.date_input("Data", value=date.today(), format="YYYY-MM-DD")
with c3:
    nr_projektu = st.text_input("Nr projektu", placeholder="NP-2025-001")

# Przychód
st.subheader("2) Przychód i parametry montażu")
c1, c2, c3 = st.columns((1, 1, 1))
with c1:
    tryb_przychodu = st.radio("Źródło przychodu", ["Wpisz ręcznie", "Z kWp × stawka"], horizontal=True, index=0)
with c2:
    waluta_przychodu = st.selectbox("Waluta przychodu", ["EUR", "PLN"], index=0)
with c3:
    dni_montazu = st.number_input("Dni montażu", min_value=0, value=0, step=1)

c1, c2, c3 = st.columns((1, 1, 1))
if tryb_przychodu == "Wpisz ręcznie":
    with c1:
        kwota_calkowita = st.number_input(f"Kwota całkowita ({waluta_przychodu})", min_value=0.0, value=0.0, step=100.0)
    kWp = st.session_state.get("kWp", 0.0)
    cena_kWp = st.session_state.get("cena_kWp", 0.0)
else:
    with c1:
        kWp = st.number_input("Ilość kWp", min_value=0.0, value=0.0, step=1.0)
    with c2:
        cena_kWp = st.number_input(f"Kwota za 1 kWp ({waluta_przychodu})", min_value=0.0, value=0.0, step=10.0)
    kwota_calkowita = kWp * cena_kWp

# Koszty podstawowe
st.subheader("3) Koszty podstawowe")
c1, c2, c3 = st.columns((1, 1, 1))
with c1:
    zus = st.number_input(f"ZUS ({waluta_przychodu})", min_value=0.0, value=0.0, step=50.0)
with c2:
    paliwo = st.number_input(f"Paliwo + amortyzacja ({waluta_przychodu})", min_value=0.0, value=0.0, step=50.0)
with c3:
    hotel_dzien = st.number_input(f"Hotel / dzień ({waluta_przychodu})", min_value=0.0, value=0.0, step=10.0)

c1, c2 = st.columns((1, 1))
with c1:
    nieprzewidziane_proc = st.slider("Koszta nieprzewidziane (% od przychodu)", 0, 50, 20, step=5)
with c2:
    nieprzewidziane_proc = st.number_input("lub wpisz własny procent", min_value=0, max_value=100, value=int(nieprzewidziane_proc), step=1)

# Pracownicy
st.subheader("4) Pracownicy (indywidualne stawki)")
cbtn1, cbtn2 = st.columns((0.22, 0.28))
with cbtn1:
    if st.button("➕ Dodaj pracownika", use_container_width=True):
        st.session_state.employees = pd.concat(
            [
                st.session_state.employees,
                pd.DataFrame([{"Imię i nazwisko": "", "Stanowisko": "", "Dni": 0, "Godz. łącznie": 0.0, "Stawka": 0.0, "Waluta": "EUR", "Wynagrodzenie": 0.0}]),
            ],
            ignore_index=True,
        )
with cbtn2:
    if st.button("🗑️ Usuń puste wiersze", use_container_width=True):
        df = st.session_state.employees
        mask = (
            df[["Imię i nazwisko", "Stanowisko"]].fillna("").apply(lambda r: "".join(r), axis=1).str.strip().astype(bool)
            | (pd.to_numeric(df.get("Dni", 0), errors="coerce").fillna(0) > 0)
            | (pd.to_numeric(df.get("Godz. łącznie", 0), errors="coerce").fillna(0) > 0)
            | (pd.to_numeric(df.get("Stawka", 0), errors="coerce").fillna(0) > 0)
        )
        st.session_state.employees = df[mask].reset_index(drop=True)

emp_df = st.data_editor(
    st.session_state.employees,
    key="employees_editor",
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
)
emp_df = _recalc_employees(emp_df)
st.session_state.employees = emp_df

sums_wages = _sum_wages_by_currency(emp_df)
if sums_wages:
    st.caption("**Suma wynagrodzeń (per waluta):** " + " • ".join(f"{cur}: {fmt2(val)}" for cur, val in sums_wages.items()))

# Dodatkowe koszta
st.subheader("5) Dodatkowe koszta (dowolna liczba pozycji)")
extra_df = st.data_editor(
    st.session_state.extra_costs,
    key="extra_costs_editor",
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={"Kwota": st.column_config.NumberColumn(format="%.2f")},
)
st.session_state.extra_costs = extra_df

# Obliczenia
przychod = float(kwota_calkowita or 0.0)
podatek = 0.055 * przychod
nieprzewidziane_kwota = (float(nieprzewidziane_proc) / 100.0) * przychod
hotele = float(hotel_dzien) * float(dni_montazu or 0)
dodatkowe_suma = _extra_costs_sum(extra_df)
razem_koszty = podatek + float(zus or 0) + float(paliwo or 0) + hotele + nieprzewidziane_kwota + dodatkowe_suma

wages_per_curr = _sum_wages_by_currency(emp_df)
wynagrodzenia_total = sum(wages_per_curr.values())  # 1:1 bez FX
saldo_po_kosztach = przychod - razem_koszty
wynagrodzenia_w_przychodzie = wynagrodzenia_total
po_wyn = saldo_po_kosztach - wynagrodzenia_w_przychodzie
pieniadze_firmy = max(0.0, 0.10 * po_wyn)
kwota_koncowa = po_wyn - pieniadze_firmy

# Podsumowanie w UI
st.subheader("6) Podsumowanie")
c1, c2 = st.columns((1, 1))
with c1:
    st.metric("Przychód", f"{fmt2(przychod)} {waluta_przychodu}")
    st.metric("Razem koszty (bez wynagrodzeń)", f"{fmt2(razem_koszty)} {waluta_przychodu}")
    st.metric("Saldo po kosztach (bez wynagrodzeń)", f"{fmt2(saldo_po_kosztach)} {waluta_przychodu}")
with c2:
    st.metric("Wynagrodzenia (łącznie)", f"{fmt2(wynagrodzenia_total)}")
    st.metric("Pieniądze firmy (10%) po wynagrodzeniach", f"{fmt2(pieniadze_firmy)} {waluta_przychodu}")
    st.metric("Kwota końcowa", f"{fmt2(kwota_koncowa)} {waluta_przychodu}")

# PDF
meta = {
    "nazwa": nazwa,
    "nr_projektu": nr_projektu,
    "data": data_doc,
    "dni_montazu": dni_montazu,
}
koszty_ctx = {
    "waluta_przychodu": waluta_przychodu,
    "podatek": podatek,
    "zus": float(zus or 0.0),
    "paliwo": float(paliwo or 0.0),
    "hotel_dzien": float(hotel_dzien or 0.0),
    "hotele": hotele,
    "nieprzewidziane_proc": float(nieprzewidziane_proc),
    "nieprzewidziane_kwota": nieprzewidziane_kwota,
    "dodatkowe_suma": dodatkowe_suma,
    "razem_koszty": razem_koszty,
    "saldo_po_kosztach": saldo_po_kosztach,
    "wynagrodzenia_w_przychodzie": wynagrodzenia_w_przychodzie,
    "pieniadze_firmy": pieniadze_firmy,
    "kwota_koncowa": kwota_koncowa,
}

st.write("---")
col_pdf1, col_pdf2 = st.columns((1, 2))
with col_pdf1:
    uploaded_logo = st.file_uploader("(opcjonalnie) Wgraj logo do znaku wodnego (PNG/JPG)", type=["png", "jpg", "jpeg"])
    if uploaded_logo:
        logo_bytes = uploaded_logo.read()
    else:
        logo_bytes = load_local_logo_bytes()

    if st.button("📄 Generuj PDF", type="primary", use_container_width=True):
        pdf_bytes = build_pdf(
            meta,
            koszty_ctx,
            st.session_state.employees,
            st.session_state.extra_costs,
            logo_bytes,  # używane wyłącznie jako znak wodny w PDF
        )
        st.download_button(
            label="⬇️ Pobierz PDF",
            data=pdf_bytes,
            file_name=f"Kosztorys_{date.today().isoformat()}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
with col_pdf2:
    st.info(
        "PDF jak wcześniej (bez logo w nagłówku), ale z **delikatnym znakiem wodnym logo** w tle. "
        "W tabeli pracowników dodano **sumy per waluta**. Nagłówki i linie są **jasnoszare**."
    )
