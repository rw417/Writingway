from muse.prompt_dialog_tabbed import PromptDialogTabbed

# gettext '_' fallback for static analysis / standalone edits
try:
    _
except NameError:
    _ = lambda s: s

class PromptPreviewDialog(PromptDialogTabbed):
    """
    Legacy wrapper for PromptDialogTabbed to maintain backwards compatibility.
    This class redirects to the new tabbed dialog implementation.
    
    All functionality is now inherited from PromptDialogTabbed.
    This wrapper ensures existing code using PromptPreviewDialog continues to work
    without requiring changes to existing imports or instantiation code.
    """
    pass
