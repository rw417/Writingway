# llm_helpers.py
"""Helper functions for LLM operations across the application."""

from PyQt5.QtWidgets import QMessageBox, QApplication
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QTextCursor
import muse.prompt_handler as prompt_handler
from settings.llm_worker import LLMWorker
from settings.llm_api_aggregator import WWApiAggregator
import logging
import threading
import re
import tiktoken

# gettext '_' fallback for static analysis / standalone edits
try:
    _
except NameError:
    _ = lambda s: s


def send_prompt_with_ui_integration(controller, prompt_config, user_input, additional_vars=None, 
                                    current_scene_text=None, extra_context=None, overrides=None):
    """
    Send a prompt to the LLM with full UI integration.
    
    Args:
        controller: The main window/controller with UI elements
        prompt_config: The prompt configuration
        user_input: The user input text (action beats)
        additional_vars: Dictionary of additional variables
        current_scene_text: Current scene text content
        extra_context: Extra context from context panel
        overrides: LLM provider/model overrides
    
    Returns:
        bool: True if prompt was sent successfully, False otherwise
    """
    # Validation
    # if not user_input:
    #     QMessageBox.warning(controller, _("LLM Prompt"), _("Please enter some action beats before sending."))
    #     return False
        
    if not prompt_config:
        QMessageBox.warning(controller, _("LLM Prompt"), _("Please select a prompt."))
        return False
    
    # Assemble the final prompt
    final_prompt = prompt_handler.assemble_final_prompt(
        prompt_config, user_input, additional_vars, current_scene_text, extra_context
    )
    
    # UI state management
    if hasattr(controller, 'bottom_stack'):
        controller.bottom_stack.preview_text.clear()
        controller.bottom_stack.send_button.setEnabled(False)
        controller.bottom_stack.preview_text.setReadOnly(True)
    
    QApplication.processEvents()
    
    # Stop any existing worker
    stop_llm_worker(controller)
    
    # Create and start new worker
    controller.worker = LLMWorker(final_prompt, overrides or {})
    
    # Connect signals - use helper functions if controller supports them
    if hasattr(controller, 'update_text'):
        controller.worker.data_received.connect(controller.update_text)
    else:
        controller.worker.data_received.connect(lambda text: update_llm_text(text, controller.bottom_stack.preview_text))
    
    if hasattr(controller, 'on_finished'):
        controller.worker.finished.connect(controller.on_finished)
    else:
        controller.worker.finished.connect(lambda: handle_llm_completion(controller, controller.bottom_stack.preview_text))
    
    # Always connect cleanup
    controller.worker.finished.connect(lambda: cleanup_llm_worker(controller))
    
    # Connect token limit handler if it exists
    if hasattr(controller, 'handle_token_limit_error'):
        controller.worker.token_limit_exceeded.connect(controller.handle_token_limit_error)
    
    controller.worker.start()
    
    return True


def gather_prompt_data_from_ui(bottom_stack, scene_editor, project_tree):
    """
    Gather all prompt-related data from UI components.
    Now uses the centralized variable system for cleaner variable management.
    
    Args:
        bottom_stack: BottomStack instance with prompt UI
        scene_editor: SceneEditor instance
        project_tree: ProjectTreeWidget instance
    
    Returns:
        dict: Dictionary containing all gathered prompt data
    """
    action_beats = bottom_stack.prompt_input.toPlainText().strip()
    prose_config = bottom_stack.prose_prompt_panel.get_prompt()
    overrides = bottom_stack.prose_prompt_panel.get_overrides()
    
    # The centralized system now handles all variables automatically
    # No need to manually collect additional_vars, current_scene_text, extra_context
    
    return {
        'user_input': action_beats,
        'prompt_config': prose_config,
        'overrides': overrides,
        'additional_vars': None,  # Legacy - now handled by centralized system
        'current_scene_text': None,  # Legacy - now handled by centralized system  
        'extra_context': None  # Legacy - now handled by centralized system
    }


def cleanup_llm_worker(controller):
    """
    Clean up LLM worker resources safely.
    
    Args:
        controller: The controller object with a worker attribute
    """
    logging.debug(f"Starting cleanup_llm_worker, worker: {id(controller.worker) if controller.worker else None}")
    try:
        if controller.worker:
            worker_id = id(controller.worker)
            if controller.worker.isRunning():
                logging.debug(f"Stopping worker {worker_id}")
                controller.worker.stop()
                controller.worker.wait(5000)
                if controller.worker.isRunning():
                    logging.warning(f"Worker {worker_id} did not stop in time; skipping termination")
            try:
                logging.debug(f"Disconnecting signals for worker {worker_id}")
                controller.worker.data_received.disconnect()
                controller.worker.finished.disconnect()
                controller.worker.token_limit_exceeded.disconnect()
            except TypeError as e:
                logging.debug(f"Signal disconnection error for worker {worker_id}: {e}")
            logging.debug(f"Scheduling worker {worker_id} for deletion")
            controller.worker.deleteLater()
            controller.worker = None
    except Exception as e:
        logging.error(f"Error cleaning up LLMWorker: {e}", exc_info=True)
        QMessageBox.critical(controller, _("Thread Error"), _("An error occurred while stopping the LLM thread: {}").format(str(e)))


def stop_llm_worker(controller):
    """
    Stop LLM worker and clean up resources.
    
    Args:
        controller: The controller object with worker and UI elements
    """
    logging.debug(f"Starting stop_llm_worker, worker: {id(controller.worker) if controller.worker else None}")
    try:
        if hasattr(controller, 'worker') and controller.worker and controller.worker.isRunning():
            logging.debug("Calling worker.stop()")
            controller.worker.stop()
            logging.debug("Calling WWApiAggregator.interrupt()")
            WWApiAggregator.interrupt()
        
        # Re-enable UI elements
        if hasattr(controller, 'bottom_stack'):
            controller.bottom_stack.send_button.setEnabled(True)
            controller.bottom_stack.preview_text.setReadOnly(False)
        
        logging.debug("Calling cleanup_llm_worker")
        cleanup_llm_worker(controller)
    except Exception as e:
        logging.error(f"Error in stop_llm_worker: {e}", exc_info=True)
        QMessageBox.critical(controller, _("Error"), _("An error occurred while stopping the LLM: {}").format(str(e)))


def handle_llm_completion(controller, preview_text_widget):
    """
    Handle LLM completion and format the output.
    
    Args:
        controller: The controller object
        preview_text_widget: The QTextEdit widget to display results
    """
    if hasattr(controller, 'bottom_stack'):
        controller.bottom_stack.send_button.setEnabled(True)
        controller.bottom_stack.preview_text.setReadOnly(False)
    
    raw_text = preview_text_widget.toPlainText()
    if not raw_text.strip():
        QMessageBox.warning(controller, _("LLM Response"), _("The LLM did not return any text. Possible token limit reached or an error occurred."))
        return
    
    # Format markdown-style text
    formatted_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", raw_text)
    formatted_text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", formatted_text)
    formatted_text = formatted_text.replace("\n", "<br>")
    preview_text_widget.setHtml(formatted_text)
    logging.debug(f"Active threads: {threading.enumerate()}")


def update_llm_text(text, preview_text_widget):
    """
    Update the preview text widget with streaming LLM output.
    
    Args:
        text: The new text to append
        preview_text_widget: The QTextEdit widget to update
    """
    cursor = preview_text_widget.textCursor()
    cursor.movePosition(QTextCursor.End)
    preview_text_widget.setTextCursor(cursor)
    preview_text_widget.insertPlainText(text)


def retry_llm_with_content(controller, prompt_config, user_input, additional_vars, content, extra_context=None):
    """
    Retry LLM request with different content (e.g., summary instead of full text).
    
    Args:
        controller: The controller object
        prompt_config: The prompt configuration
        user_input: User input text
        additional_vars: Additional variables
        content: Replacement content (e.g., summary)
        extra_context: Extra context
    """
    final_prompt = prompt_handler.assemble_final_prompt(
        prompt_config.get("text") if isinstance(prompt_config, dict) else prompt_config,
        user_input, additional_vars, content, extra_context
    )
    
    if hasattr(controller, 'bottom_stack'):
        controller.bottom_stack.preview_text.clear()
        controller.bottom_stack.preview_text.setReadOnly(True)
    
    controller.worker = LLMWorker(final_prompt, prompt_config)
    controller.worker.data_received.connect(lambda text: update_llm_text(text, controller.bottom_stack.preview_text))
    controller.worker.finished.connect(lambda: handle_llm_completion(controller, controller.bottom_stack.preview_text))
    controller.worker.finished.connect(lambda: cleanup_llm_worker(controller))
    
    # Connect token limit handler if it exists
    if hasattr(controller, 'show_token_limit_dialog'):
        controller.worker.token_limit_exceeded.connect(controller.show_token_limit_dialog)
    
    controller.worker.start()


def get_truncated_text(full_text, max_tokens_ratio=0.5):
    """
    Truncate text to fit within token limits.
    
    Args:
        full_text: The full text to truncate
        max_tokens_ratio: Ratio of max tokens to use (default 0.5 = 50%)
    
    Returns:
        Truncated text
    """
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(full_text)
        max_tokens = int(len(tokens) * max_tokens_ratio)
        truncated = encoding.decode(tokens[-max_tokens:])
        return truncated
    except Exception:
        # Fallback: simple character-based truncation
        return full_text[-int(len(full_text) * max_tokens_ratio):]
