import os
import sys
import traceback
import faulthandler
import signal

# Ensure repository root is on sys.path so local packages can be imported when tests run
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# Run Qt in offscreen mode to avoid needing a display
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

# Enable fault handler and register to dump traceback on SIGSEGV
faulthandler.enable(all_threads=True)
try:
    faulthandler.register(signal.SIGSEGV, file=open('segfault_trace.txt', 'w'), all_threads=True)
except Exception:
    # Registration may fail on some platforms; continue anyway
    pass

try:
    from PyQt5.QtWidgets import QApplication
    from compendium.enhanced_compendium import EnhancedCompendiumWindow

    app = QApplication([])
    w = EnhancedCompendiumWindow("testproject")

    # Work with the model directly to avoid interactive dialogs
    m = w.model
    # Ensure test category is unique
    test_cat = "SmokeCat"
    test_entry = "SmokeEntry"
    # Remove any existing test entry/category
    # Rebuild categories excluding our test ones
    cats = [c for c in m.get_categories() if c.get('name') != test_cat]
    m.compendium_data['categories'] = cats

    # Add category and entry
    m.add_category(test_cat)
    payload = {"name": test_entry, "content": {"description": "desc"}, "uuid": "test-uuid-1"}
    m.add_entry(test_cat, payload)
    m.save()

    # Populate the UI tree
    w.populate_compendium()

    # Find and select the entry
    w.find_and_select_entry(test_entry)
    sel = w.tree.currentItem()
    print("current_item_text:", sel.text(0) if sel else None)

    # Now delete via model and repopulate
    m.delete_entry(test_entry)
    m.save()
    w.populate_compendium()

    # Verify deletion
    found_after = False
    for i in range(w.tree.topLevelItemCount()):
        cat = w.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            if cat.child(j).text(0) == test_entry:
                found_after = True

    print("found_after_delete:", found_after)
    print("PASS")
    sys.exit(0)

except Exception as e:
    print("EXCEPTION:", str(e))
    traceback.print_exc()
    sys.exit(2)
