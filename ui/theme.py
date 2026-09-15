"""One paper-and-brick palette for every Gradio appearance mode."""
from __future__ import annotations

import gradio as gr


def build_theme():
    brick = gr.themes.colors.Color(
        c50="#f4ecdf", c100="#ebd6c8", c200="#dbb5a3", c300="#c9957f",
        c400="#b7775e", c500="#a85b45", c600="#87443a", c700="#75392f",
        c800="#633128", c900="#52322a", c950="#382b24", name="journal_brick",
    )
    paper = gr.themes.colors.Color(
        c50="#f4ecdf", c100="#ebe1d2", c200="#dfd5c6", c300="#d0c3b2",
        c400="#ad9681", c500="#887363", c600="#695548", c700="#584539",
        c800="#49372e", c900="#382b24", c950="#2a211b", name="journal_paper",
    )
    theme = gr.themes.Base(
        primary_hue=brick, secondary_hue=brick, neutral_hue=paper,
        font=["Microsoft YaHei", "Arial", "sans-serif"],
        font_mono=["Consolas", "monospace"],
    ).set(
        body_background_fill="var(--rj-bg)", body_text_color="var(--rj-text)",
        body_text_color_subdued="var(--rj-muted)",
        background_fill_primary="var(--rj-paper-light)",
        background_fill_secondary="var(--rj-surface)",
        border_color_primary="var(--rj-rule)", border_color_accent="var(--rj-border)",
        border_color_accent_subdued="var(--rj-rule)",
        color_accent="var(--rj-action)", color_accent_soft="var(--rj-highlight)",
        link_text_color="var(--rj-action)", link_text_color_hover="var(--rj-border)",
        link_text_color_active="var(--rj-border)", link_text_color_visited="var(--rj-action)",
        code_background_fill="var(--rj-surface)",
        block_background_fill="var(--rj-paper-light)",
        block_border_color="var(--rj-rule)", block_border_width="1px",
        block_radius="var(--rj-radius-md)", block_shadow="none", block_padding="16px",
        block_label_background_fill="var(--rj-paper-light)",
        block_label_text_color="var(--rj-muted)", block_label_border_width="0px",
        block_label_shadow="none", block_label_text_weight="600",
        block_title_background_fill="var(--rj-surface)",
        block_title_text_color="var(--rj-text)", block_title_border_width="0px",
        block_info_text_color="var(--rj-muted)",
        panel_background_fill="var(--rj-surface)", panel_border_color="var(--rj-rule)",
        panel_border_width="1px", container_radius="var(--rj-radius-lg)",
        layout_gap="16px", form_gap_width="12px",
        accordion_text_color="var(--rj-text)",
        input_background_fill="var(--rj-paper-light)",
        input_background_fill_focus="var(--rj-paper-light)",
        input_background_fill_hover="var(--rj-paper-light)",
        input_border_color="var(--rj-rule)", input_border_color_focus="var(--rj-action)",
        input_border_color_hover="var(--rj-border)", input_border_width="1px",
        input_radius="var(--rj-radius-sm)", input_shadow="none",
        input_shadow_focus="0 0 0 2px var(--rj-action)",
        input_placeholder_color="var(--rj-muted)",
        checkbox_background_color="var(--rj-paper-light)",
        checkbox_background_color_hover="var(--rj-surface)",
        checkbox_background_color_focus="var(--rj-paper-light)",
        checkbox_background_color_selected="var(--rj-action)",
        checkbox_border_color="var(--rj-border)", checkbox_border_color_focus="var(--rj-action)",
        checkbox_border_color_hover="var(--rj-action)", checkbox_border_color_selected="var(--rj-action)",
        checkbox_label_background_fill="var(--rj-paper-light)",
        checkbox_label_background_fill_hover="var(--rj-surface)",
        checkbox_label_background_fill_selected="var(--rj-surface)",
        checkbox_label_border_color="var(--rj-rule)",
        checkbox_label_border_color_hover="var(--rj-border)",
        checkbox_label_border_color_selected="var(--rj-action)",
        checkbox_label_text_color="var(--rj-text)", checkbox_label_text_color_selected="var(--rj-action)",
        error_background_fill="var(--rj-paper-light)", error_border_color="var(--rj-danger-text)",
        error_text_color="var(--rj-danger-text)", error_icon_color="var(--rj-danger-text)",
        loader_color="var(--rj-action)", slider_color="var(--rj-action)",
        stat_background_fill="var(--rj-surface)", table_text_color="var(--rj-text)",
        table_border_color="var(--rj-rule)", table_even_background_fill="var(--rj-surface)",
        table_odd_background_fill="var(--rj-paper-light)", table_row_focus="var(--rj-highlight)",
        table_radius="var(--rj-radius-sm)",
        button_border_width="2px", button_large_radius="var(--rj-radius-md)",
        button_medium_radius="var(--rj-radius-md)", button_small_radius="var(--rj-radius-md)",
        button_large_padding="12px 20px", button_medium_padding="10px 16px",
        button_small_padding="8px 12px", button_transform_hover="none",
        button_transform_active="translate(var(--rj-press-distance), var(--rj-press-distance))",
        button_transition="background-color var(--rj-duration) ease, transform var(--rj-duration) ease, box-shadow var(--rj-duration) ease",
    )
    for variant, fill, text in (
        ("primary", "var(--rj-action)", "var(--rj-on-action)"),
        ("secondary", "var(--rj-paper-light)", "var(--rj-text)"),
        ("cancel", "var(--rj-paper-light)", "var(--rj-danger-text)"),
    ):
        theme.set(**{
            f"button_{variant}_background_fill": fill,
            f"button_{variant}_background_fill_hover": "var(--rj-action-hover)" if variant == "primary" else "var(--rj-surface)",
            f"button_{variant}_text_color": text,
            f"button_{variant}_text_color_hover": text,
            f"button_{variant}_border_color": "var(--rj-border)",
            f"button_{variant}_border_color_hover": "var(--rj-border)",
            f"button_{variant}_shadow": "var(--rj-shadow-sm)",
            f"button_{variant}_shadow_hover": "var(--rj-shadow-sm)",
            f"button_{variant}_shadow_active": "var(--rj-shadow-pressed)",
        })
    # Gradio can retain .dark from the OS, URL or a previous visit. Give every
    # dark token the same value so these preferences never change the palette.
    values = theme.to_dict()["theme"]
    theme.set(**{key: values[key[:-5]] for key in values if key.endswith("_dark")})
    theme.name = "retro_journal"
    return theme
