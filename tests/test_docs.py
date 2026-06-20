"""Stage 3 (docs) UI contracts — source-level checks for the docs editor chrome. Behavioral docs
flows are exercised in the ui-3 audit/Playwright scripts."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


class ToolbarSplitTests(unittest.TestCase):
    def test_word_count_pushed_right(self):
        # the cut is between the doc name and the word count → stats + actions go right
        self.assertRegex(CSS, r"\.docs-editor-head\s+\.wiki-stats\s*\{[^}]*margin-left:\s*auto")

    def test_doc_name_has_breathing_room(self):
        self.assertRegex(CSS, r"\.docs-editor-head\s+\.wiki-current\s*\{[^}]*margin-left:")

    def test_mode_toggle_reads_clearly(self):
        # the current view mode is the one button styled in the accent
        self.assertRegex(CSS, r"#wiki-mode-toggle\s*\{[^}]*var\(--accent\)")

    def test_header_wraps_gracefully(self):
        self.assertRegex(CSS, r"\.docs-editor-head\s*\{[^}]*flex-wrap:\s*wrap")


VAULTMD = (ROOT / "static" / "js" / "vaultmd.js").read_text(encoding="utf-8")


class PanelAccordionTests(unittest.TestCase):
    def test_close_helper_exists(self):
        self.assertIn("function _closeOtherPanels", VAULTMD)
        self.assertIn("_SIDE_PANELS", VAULTMD)

    def test_outline_props_query_are_mutually_exclusive(self):
        # every panel toggle goes through the one shared helper, which closes the others
        # (so you never see two glowing-but-closed panels). query keeps its own body but still
        # calls _closeOtherPanels; the rest delegate to _togglePanel.
        self.assertIn("function _togglePanel", VAULTMD)
        self.assertIn("_closeOtherPanels('wiki-query')", VAULTMD)
        for fn in ("toggleOutline", "toggleProps"):
            i = VAULTMD.index(f"function {fn}")
            self.assertIn("_togglePanel(", VAULTMD[i: i + 200])

    def test_registry_covers_the_main_panels(self):
        for pid in ("wiki-outline", "wiki-props", "wiki-query", "wiki-history", "wiki-comments"):
            self.assertIn(pid, VAULTMD)


class ImageDialogTests(unittest.TestCase):
    """ui-3d — the img toolbar button opens a paste-URL / upload dialog (not raw text)."""

    def test_dialog_function_exists(self):
        self.assertIn("function openImageDialog", VAULTMD)
        self.assertIn("image: (b) => openImageDialog(b)", VAULTMD)

    def test_dialog_offers_url_and_upload(self):
        self.assertIn("wiki-img-url", VAULTMD)
        self.assertIn("wiki-img-file", VAULTMD)
        self.assertIn('type="file"', VAULTMD)
        self.assertIn("accept=\"image/*\"", VAULTMD)

    def test_upload_routes_through_vault_asset(self):
        # uploaded file → vault asset → ![[ ]] embed
        self.assertRegex(VAULTMD, r"uploadImage\(f\)[\s\S]{0,80}!\[\[")

    def test_dialog_styled(self):
        self.assertRegex(CSS, r"\.wiki-img-pop\b")


class LinkInteractionTests(unittest.TestCase):
    """ui-3e — rendered links get custom (non-native) UI in the live editor."""

    def test_cmd_click_opens(self):
        self.assertIn("a.cm-link", VAULTMD)
        self.assertRegex(VAULTMD, r"metaKey \|\| e\.ctrlKey")
        self.assertIn("window.open(a.getAttribute('href')", VAULTMD)

    def test_hover_tooltip(self):
        self.assertIn("function showUrlTip", VAULTMD)
        self.assertIn("wiki-url-tip", VAULTMD)

    def test_tooltip_styled(self):
        self.assertRegex(CSS, r"\.wiki-url-tip\b")

    def test_link_is_themed_not_native(self):
        # accent colour + no native underline by default (hover only)
        self.assertRegex(CSS, r"\.cm-link\s*\{[^}]*var\(--accent\)")


class TableStyleTests(unittest.TestCase):
    """ui-3f — live tables are real, bordered, header-emphasised."""

    def test_table_cells_bordered(self):
        self.assertRegex(CSS, r"\.cm-table\s+th[^{}]*\{[^}]*border:\s*1px")

    def test_header_emphasised(self):
        self.assertRegex(CSS, r"\.cm-table\s+th\s*\{[^}]*font-weight:\s*600")

    def test_header_has_fill(self):
        self.assertRegex(CSS, r"\.cm-table\s+th\s*\{[^}]*background:\s*var\(--panel\)")

    def test_collapsed_borders(self):
        self.assertRegex(CSS, r"\.cm-table\s*\{[^}]*border-collapse:\s*collapse")


class SelectionColumnTests(unittest.TestCase):
    """ui-3h — selection can't bleed past the centered column: the WHOLE editor is
    capped (not just .cm-content), so CM's selection layer stays inside it."""

    def test_editor_capped_not_just_content(self):
        self.assertRegex(CSS, r"\.wiki-live\s+\.cm-editor\s*\{[^}]*max-width:\s*820px")

    def test_live_centers_the_column(self):
        self.assertRegex(CSS, r"\.wiki-live\s*\{[^}]*justify-content:\s*center")


class RemovedButtonsTests(unittest.TestCase):
    """ui-3n — Publish + per-vault CSS buttons (and their wiring) are gone."""

    def test_publish_button_gone(self):
        self.assertNotIn("wiki-publish-btn", INDEX)
        self.assertNotIn("togglePublish", VAULTMD)

    def test_css_button_and_panel_gone(self):
        self.assertNotIn("wiki-theme-btn", INDEX)
        self.assertNotIn('id="wiki-theme"', INDEX)
        self.assertNotIn("toggleTheme", VAULTMD)
        self.assertNotIn("_injectVaultTheme", VAULTMD)

    def test_no_dead_share_imports(self):
        # the share helpers were only used by publish
        self.assertNotIn("unshareResource", VAULTMD)


class ContextMenuTests(unittest.TestCase):
    """ui-3i — custom right-click menu replaces the native one in the docs editor."""

    def test_menu_wired_to_both_editors(self):
        self.assertIn("function openDocsContextMenu", VAULTMD)
        self.assertIn("$('wiki-live')?.addEventListener('contextmenu', openDocsContextMenu)", VAULTMD)
        self.assertIn("$('wiki-source')?.addEventListener('contextmenu', openDocsContextMenu)", VAULTMD)

    def test_menu_has_clipboard_format_and_ai(self):
        for act in ("'cut'", "'copy'", "'paste'", "ai-rewrite", "ai-summarize", "ai-fix"):
            self.assertIn(act, VAULTMD)

    def test_ai_actions_hit_the_snippet_route(self):
        self.assertIn("/api/vault-md/ai-snippet", VAULTMD)

    def test_menu_styled(self):
        self.assertRegex(CSS, r"\.ctx-sep\b")
        self.assertRegex(CSS, r"\.docs-ctx\b")


class MovedToHomeTests(unittest.TestCase):
    """ui-3k — canvas/board/tasks/bookmark leave the in-doc toolbar for the docs home."""

    def test_in_doc_buttons_removed(self):
        for bid in ("wiki-canvas-btn", "wiki-board-btn", "wiki-bookmark-btn"):
            self.assertNotIn(bid, INDEX)

    def test_home_gains_new_canvas_board_tasks(self):
        for bid in ("wiki-home-canvas", "wiki-home-board", "wiki-home-tasks"):
            self.assertIn(bid, INDEX)
        self.assertIn("wiki-home-canvas", VAULTMD)
        self.assertIn("wiki-home-board", VAULTMD)

    def test_cards_are_bookmarkable(self):
        self.assertIn("docs-card-star", VAULTMD)
        self.assertIn("function _bookmarkPath", VAULTMD)
        self.assertRegex(CSS, r"\.docs-card-star\b")

    def test_old_in_doc_bookmark_handler_gone(self):
        self.assertNotIn("function toggleBookmark", VAULTMD)
        self.assertNotIn("_syncBookmarkBtn", VAULTMD)


class HistoryPanelTests(unittest.TestCase):
    """ui-3l — version-history panel redesign: classed rows, real padding."""

    def test_rows_use_classes_not_inline_styles(self):
        self.assertIn("wiki-rev-row", VAULTMD)
        self.assertIn("wiki-rev-when", VAULTMD)
        self.assertIn("wiki-rev-diff-pre", VAULTMD)
        # the old cramped inline-styled row markup is gone
        self.assertNotIn('style="display:flex;align-items:center;gap:0.5rem;padding:0.25rem 0', VAULTMD)

    def test_panel_padded_and_roomy(self):
        self.assertRegex(CSS, r"#wiki-history\s*\{[^}]*padding:")
        self.assertRegex(CSS, r"#wiki-history\s*\{[^}]*width:\s*2\d\dpx")

    def test_rows_aligned(self):
        self.assertRegex(CSS, r"\.wiki-rev-row\s*\{[^}]*display:\s*flex")
        self.assertRegex(CSS, r"\.wiki-rev-btn:nth-of-type\(1\)\s*\{[^}]*margin-left:\s*auto")

    def test_diff_block_readable(self):
        self.assertRegex(CSS, r"\.wiki-rev-diff-pre\b")


class CommentFlowTests(unittest.TestCase):
    """ui-3m — the select-text→comment flow works in the default live editor."""

    def test_fab_wired_to_live_editor(self):
        self.assertIn("$('wiki-live')?.addEventListener('mouseup', _onDocSelect)", VAULTMD)
        self.assertIn("function _onDocSelect", VAULTMD)
        self.assertNotIn("_onPreviewSelect", VAULTMD)

    def test_fab_is_viewport_fixed(self):
        # was position:absolute with window-scroll math (mis-placed in the scrolling editor)
        self.assertRegex(CSS, r"\.wiki-comment-fab\s*\{[^}]*position:\s*fixed")

    def test_empty_copy_points_at_the_editor(self):
        self.assertIn("select any text in the editor", VAULTMD)
        self.assertNotIn("select text in the preview to add one", VAULTMD)


class SplitViewTests(unittest.TestCase):
    """ui-3o — split view: doc picker (open/all), ~50/50, draggable divider."""

    def test_picker_with_scope(self):
        self.assertIn("function openSplitPicker", VAULTMD)
        self.assertIn("split-picker", VAULTMD)
        self.assertIn("data-s=\"open\"", VAULTMD)
        self.assertIn("data-s=\"all\"", VAULTMD)

    def test_draggable_divider(self):
        self.assertIn("function _initSplitDivider", VAULTMD)
        self.assertIn("wiki-split-divider", INDEX)
        self.assertRegex(CSS, r"\.wiki-split-divider\s*\{[^}]*cursor:\s*col-resize")

    def test_fifty_fifty_default(self):
        self.assertRegex(CSS, r"#wiki-view\.split-on\s+\.wiki-split-pane\s*\{[^}]*var\(--split,\s*50%\)")

    def test_split_selector_targets_the_id(self):
        # the element is #wiki-view (not .wiki-view) — the old class selector never matched
        self.assertNotRegex(CSS, r"\.wiki-view\.split-on")


class ExportFidelityTests(unittest.TestCase):
    """ui-3p — the export stylesheet keeps tables/links/code faithful to live/preview."""

    def test_export_css_covers_tables_links_code(self):
        css = VAULTMD.replace(" ", "")
        self.assertIn("th,td{border:1px", css)
        self.assertIn("a{color:", css)
        self.assertIn("pre{", css)
        self.assertIn(".md-callout{", css)
        self.assertIn("img{max-width:100%", css)

    def test_export_builds_from_the_rendered_preview(self):
        # export = the same mdToHtml render the user sees, not a separate lossy path
        self.assertIn("$('wiki-preview').innerHTML", VAULTMD)


class TabsRedesignTests(unittest.TestCase):
    """ui-3q — tabs: squircle on open, plain inactive + separators, no dead gutter,
    deleted docs leave the strip."""

    def test_open_tab_squircle_inactive_plain(self):
        self.assertRegex(CSS, r"\.wiki-tab\s*\{[^}]*border:\s*1px solid transparent")
        self.assertRegex(CSS, r"\.wiki-tab\.active\s*\{[^}]*border-color:\s*var\(--accent\)")
        self.assertRegex(CSS, r"\.wiki-tab\s*\{[^}]*border-radius:\s*7px")

    def test_separator_between_inactive_tabs(self):
        self.assertRegex(CSS, r"\.wiki-tab:not\(\.active\)\s*\+\s*\.wiki-tab:not\(\.active\)::before")

    def test_no_dead_left_gutter(self):
        # was padding: 0 clamp(1.5rem, 12%, 7rem) — a big empty left gap
        self.assertNotRegex(CSS, r"\.wiki-tabs\s*\{[^}]*clamp\(1\.5rem,\s*12%")

    def test_delete_drops_doc_from_tabs(self):
        # toolbar delete routes through closeTab; tree delete filters _tabs
        self.assertRegex(VAULTMD, r"async function deleteCurrent[\s\S]{0,260}closeTab\(p\)")
        self.assertIn("_tabs = _tabs.filter(x => x !== path && !x.startsWith(path + '/'))", VAULTMD)


class OutlineClarityTests(unittest.TestCase):
    """ui-3r — outline populates from headings with level emphasis + a real empty explainer."""

    def test_empty_explainer_is_helpful(self):
        self.assertIn("no headings yet", VAULTMD)
        self.assertNotIn('<div class="wiki-outline-empty">no headings</div>', VAULTMD)

    def test_header_shows_count(self):
        self.assertRegex(VAULTMD, r"outline · \$\{heads\.length\}")

    def test_levels_carry_a_class(self):
        self.assertIn("wiki-outline-item lvl${h.level}", VAULTMD)
        self.assertRegex(CSS, r"\.wiki-outline-item\.lvl1\s*\{[^}]*font-weight")

    def test_deeper_levels_get_a_rail(self):
        self.assertRegex(CSS, r"\.wiki-outline-item\.lvl3[^{]*\{[^}]*border-left")


class ExplainerTests(unittest.TestCase):
    """ui-3s — todo-extraction explainer popup + backlinks purpose header."""

    def test_todos_opens_an_explainer_not_a_direct_run(self):
        self.assertIn("function openTodosExplainer", VAULTMD)
        self.assertIn("$('wiki-todos-btn')?.addEventListener('click', e => openTodosExplainer(e.currentTarget))", VAULTMD)
        self.assertIn("function _runExtractTodos", VAULTMD)

    def test_todos_explainer_describes_the_action(self):
        self.assertIn("extract to-dos with AI", VAULTMD)
        self.assertIn("wiki-todos-go", VAULTMD)

    def test_backlinks_has_a_purpose_header(self):
        self.assertIn("wiki-bl-explainer", VAULTMD)
        self.assertRegex(CSS, r"\.wiki-bl-explainer\b")

    def test_backlinks_empty_copy_is_actionable(self):
        self.assertIn("nothing links here yet", VAULTMD)
        self.assertNotIn("'<span class=\"wiki-bl-empty\">no backlinks</span>'", VAULTMD)


class DocsSettingsTests(unittest.TestCase):
    """ui-3t — docs settings (AI status + model picker); the guide is gone."""

    def test_guide_removed(self):
        self.assertNotIn("wiki-help-btn", INDEX)
        self.assertNotIn('id="wiki-help"', INDEX)
        self.assertNotIn("wiki-empty-guide", INDEX)
        self.assertNotIn("wiki-help", VAULTMD)

    def test_settings_button_and_popup(self):
        self.assertIn("wiki-docs-settings", INDEX)
        self.assertIn("function openDocsSettings", VAULTMD)

    def test_popup_has_status_and_model_picker(self):
        self.assertIn("wds-status", VAULTMD)
        self.assertIn("wds-model", VAULTMD)
        self.assertIn("docs_ai_model", VAULTMD)
        self.assertRegex(CSS, r"\.wds-status\.ok\b")

    def test_status_reads_the_model_list(self):
        self.assertIn("/api/models", VAULTMD)
        self.assertIn("AI ready", VAULTMD)


if __name__ == "__main__":
    unittest.main()
