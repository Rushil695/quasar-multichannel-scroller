#!/usr/bin/env python3
"""
Plot EEG (µV) + ECG (mV) + CM (µV) as an interactive, scrollable Plotly HTML.
- Ignores CSV lines starting with '#'
- First non-comment line is treated as the header
- ECG columns X1:LEOG / X2:REOG are converted to mV (from µV) and shown in a top subplot
- CM is shown on the secondary y-axis in the top subplot (kept in µV)
- EEG channels (µV) are shown in the bottom subplot
"""

from __future__ import annotations
import argparse
import io
import os
from typing import Dict, List, Tuple
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


EEG_CANONICAL = {"Fz","Cz","P3","C3","F3","F4","C4","P4","Fp1","Fp2","T3","T4","T5","T6","O1","O2","F7","F8","A1","A2","Pz"}
IGNORE_EXACT = {"Trigger","Time_Offset","ADC_Status","ADC_Sequence","Event","Comments"}
ECG_MAP = {"X1:LEOG": "ECG_L",#for Left ECG
"X2:REOG": "ECG_R",#for Right ECG
}

def read_quasar_csv(path: str) -> pd.DataFrame:
    """
    Read a CSV where:
      - Lines starting with '#' are comments to be ignored
      - The first non-comment line is the header
    Returns a pandas DataFrame.
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    if not lines:
        raise ValueError("No data found after stripping comment lines.")
    header = lines[0]
    body = "".join(lines[1:])
    csv_buf = io.StringIO(header + body)
    df = pd.read_csv(csv_buf)
    return df


def classify_columns(df: pd.DataFrame) -> Tuple[str, List[str], Dict[str, str], str, List[str]]:
    """
    Identify time, EEG, ECG, CM, and ignored columns.
    Returns: (time_col, eeg_cols, ecg_cols_map, cm_col, ignored_cols)
    - ecg_cols_map maps original CSV names to canonical short names (ECG_L/ECG_R).
    """
    cols = list(df.columns)

    # Time column: prefer anything containing "time" (case-insensitive)
    time_col = None
    for c in cols:
        if "time" in str(c).lower():
            time_col = c
            break
    if time_col is None:
        # Fallback: first column
        time_col = cols[0]

    ignored = []
    eeg_cols = []
    cm_col = None
    ecg_cols_map: Dict[str,str] = {}

    for c in cols:
        if c == time_col:
            continue
        if c in IGNORE_EXACT or str(c).startswith("X3:"):
            ignored.append(c)
            continue
        if c == "CM":
            cm_col = c
            continue
        if c in ECG_MAP:
            ecg_cols_map[c] = ECG_MAP[c]
            continue
        # Heuristic: if it's in our canonical EEG set, classify as EEG.
        if c in EEG_CANONICAL:
            eeg_cols.append(c)
            continue
        # Otherwise, if it looks like an EEG lead label (letters+digits) and not in ignore, treat as EEG.
        if isinstance(c, str) and c and c[0].isalpha() and c not in ecg_cols_map and not c.startswith("X3:"):
            # Be permissive; the legend remains clickable.
            eeg_cols.append(c)

    return time_col, eeg_cols, ecg_cols_map, cm_col, ignored


def maybe_downsample(df: pd.DataFrame, time_col: str, max_points: int) -> pd.DataFrame:
    """
    Basic stride downsampling to keep the page snappy on extremely large files.
    """
    if max_points is None or len(df) <= max_points:
        return df
    stride = max(1, len(df) // max_points)
    return df.iloc[::stride, :].reset_index(drop=True)


def build_figure(df: pd.DataFrame, time_col: str, eeg_cols: List[str], ecg_cols_map: Dict[str, str], cm_col: str | None, include_eeg: bool, include_ecg: bool, include_cm: bool, eeg_include: List[str] | None = None,ecg_include: List[str] | None = None) -> go.Figure:
    """
    Create a two-row subplot figure:
      Row 1 (shared x): ECG (mV, left) + CM (µV, right)
      Row 2: EEG (µV)
    """
    specs = [[{"secondary_y": True}], [{}]]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, specs=specs,
                        row_heights=[0.35, 0.65], vertical_spacing=0.06)

    t = df[time_col]

    # Top subplot: ECG (left, mV) + CM (right, microV)
    if include_ecg and ecg_cols_map:
        for orig_name, short_name in ecg_cols_map.items():
            if ecg_include and short_name not in ecg_include and orig_name not in ecg_include:
                continue
            if orig_name not in df.columns:
                continue
            # Convert µV → mV
            y_mv = df[orig_name] / 1000.0
            fig.add_trace(
                go.Scattergl(
                    x=t, y=y_mv, name=f"{short_name} (mV)", mode="lines", hovertemplate="t=%{x:.3f}s<br>%{y:.3f} mV"
                ),
                row=1, col=1, secondary_y=False
            )

    if include_cm and cm_col and cm_col in df.columns:
        fig.add_trace(
            go.Scattergl(
                x=t, y=df[cm_col], name="CM (µV)", mode="lines", hovertemplate="t=%{x:.3f}s<br>%{y:.1f} µV"
            ),
            row=1, col=1, secondary_y=True
        )

    # Bottom subplot: EEG (micro V)
    if include_eeg and eeg_cols:
        keep = set(eeg_include) if eeg_include else None
        for c in eeg_cols:
            if keep and (c not in keep):
                continue
            if c not in df.columns:
                continue
            fig.add_trace(go.Scattergl(x=t, y=df[c], name=f"{c} (µV)", mode="lines", hovertemplate="t=%{x:.3f}s<br>%{y:.1f} µV"),row=2, col=1)

    # Axes & layout
    fig.update_yaxes(title_text="ECG (mV)", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="CM (µV)", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="EEG (µV)", row=2, col=1)

    fig.update_xaxes(title_text="Time (s)", row=2, col=1, rangeslider=dict(visible=True))

    fig.update_layout(
        template="plotly_white",
        title="QUASAR Multichannel Plot — EEG & ECG",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
        margin=dict(l=60, r=60, t=140, b=30),
        hovermode="x unified"
    )

    return fig


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrollable multichannel EEG+ECG plot generator (Plotly HTML).")
    p.add_argument("--csv", required=True, help="Path to CSV (lines starting with '#' are ignored).")
    p.add_argument("--out", default="out/quasar_plot.html", help="Output HTML file path.")
    p.add_argument("--max-points", type=int, default=None, help="Optional downsample to at most N points.")
    p.add_argument("--eeg", dest="include_eeg", action="store_true", help="Include EEG traces (default: on).")
    p.add_argument("--no-eeg", dest="include_eeg", action="store_false", help="Exclude EEG traces.")
    p.set_defaults(include_eeg=True)

    p.add_argument("--ecg", dest="include_ecg", action="store_true", help="Include ECG traces (default: on).")
    p.add_argument("--no-ecg", dest="include_ecg", action="store_false", help="Exclude ECG traces.")
    p.set_defaults(include_ecg=True)

    p.add_argument("--cm", dest="include_cm", action="store_true", help="Include CM trace (default: on).")
    p.add_argument("--no-cm", dest="include_cm", action="store_false", help="Exclude CM trace.")
    p.set_defaults(include_cm=True)

    p.add_argument("--eeg-include", type=str, default=None,
                   help="Comma-separated EEG channel allow-list (e.g., 'Fz,Cz,P3')")
    p.add_argument("--ecg-include", type=str, default=None,
                   help="Comma-separated ECG allow-list (accepts canonical 'ECG_L,ECG_R' or raw names 'X1:LEOG').")
    return p.parse_args()


def main():
    args = parse_args()

    df = read_quasar_csv(args.csv)
    time_col, eeg_cols, ecg_cols_map, cm_col, ignored = classify_columns(df)

    if args.max_points is not None:
        df = maybe_downsample(df, time_col=time_col, max_points=args.max_points)

    eeg_include = [s.strip() for s in args.eeg_include.split(",")] if args.eeg_include else None
    ecg_include = [s.strip() for s in args.ecg_include.split(",")] if args.ecg_include else None

    fig = build_figure(
        df=df,
        time_col=time_col,
        eeg_cols=eeg_cols,
        ecg_cols_map=ecg_cols_map,
        cm_col=cm_col,
        include_eeg=args.include_eeg,
        include_ecg=args.include_ecg,
        include_cm=args.include_cm,
        eeg_include=eeg_include,
        ecg_include=ecg_include
    )

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.write_html(out_path, include_plotlyjs="cdn")
    print(f"Wrote interactive HTML to: {out_path}")


if __name__ == "__main__":
    main()
