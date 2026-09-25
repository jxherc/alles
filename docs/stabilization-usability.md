# Usability observations

These observations come from task walkthroughs on the isolated synthetic instance,
using visible controls and native Mac Safari 27.0 accessibility output. They do not
certify the complete visual or device matrix.

| Task | Observed result | Follow-up |
| --- | --- | --- |
| Leave an unsaved document, return, reload and resume it | The exact mixed-language draft survived. Reload clearly separated the saved document from the recoverable local draft. | Keep this recovery path visible. |
| Go from a document to Home, then reload | Before STAB-005, reload reopened Docs because the old URL remained. The repair keeps Home selected and Back restores the original document. | Covered by the navigation regressions. |
| Record a Health measurement | The entry action was available after opening health log. A synthetic 74.25 kg record persisted exactly after reload. The screen rounds it to 74.3 kg. | Preserve exact values when editing; distinguish summary rounding from detailed record values. |
| Correct that Health measurement | The record offered delete, with no visible edit action. Source inspection after the walkthrough confirmed an unused edit API. | STAB-006; repair in the specialist batch. |
| Find the main Health action | The overview shows both health log and open health history, plus repeated summaries. Creating an entry takes a further view change. | Simplify this overview in the specialist layout batch; keep privacy boundaries clear. |

The last row is a design change, separate from the confirmed functional defects.
