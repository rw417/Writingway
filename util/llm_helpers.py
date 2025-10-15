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
from util.llm_markdown_to_html import markdown_to_html

# gettext '_' fallback for static analysis / standalone edits
if "_" not in globals():
    _ = lambda s: s


def _default_set_worker(controller, worker):
    if hasattr(controller, "worker"):
        controller.worker = worker


def start_llm_stream(
    controller,
    *,
    prompt,
    overrides=None,
    conversation_history=None,
    on_chunk=None,
    on_finish=None,
    on_token_limit=None,
    on_cleanup=None,
    cleanup_handler=None,
    set_worker_callback=None,
):
    """Create and start an LLMWorker stream with customizable callbacks.

    Args:
        controller: Object owning the worker (must allow attribute assignment or set callback)
        prompt: Prompt string OR conversation payload list passed to LLMWorker
        overrides: Provider/model overrides dict
        conversation_history: Optional conversation history for chat-style requests
        on_chunk: Callable invoked with each streamed text chunk
        on_finish: Callable invoked after the worker finishes successfully
        on_token_limit: Callable invoked with error text when token limit exceeded
        on_cleanup: Callable invoked after cleanup is performed
        set_worker_callback: Optional callable to assign/store the worker

    Returns:
        LLMWorker: The started worker instance
    """

    stop_llm_worker(controller)

    worker = LLMWorker(prompt, overrides or {}, conversation_history)

    if set_worker_callback:
        set_worker_callback(worker)
    else:
        _default_set_worker(controller, worker)

    if on_chunk:
        worker.data_received.connect(on_chunk)
    elif hasattr(controller, "update_text"):
        worker.data_received.connect(controller.update_text)

    if on_token_limit and hasattr(worker, "token_limit_exceeded"):
        worker.token_limit_exceeded.connect(on_token_limit)
    elif hasattr(controller, "handle_token_limit_error"):
        worker.token_limit_exceeded.connect(controller.handle_token_limit_error)

    cleanup_fn = cleanup_handler or (lambda ctrl: cleanup_llm_worker(ctrl))

    def _finish_wrapper():
        try:
            if on_finish:
                on_finish()
            elif hasattr(controller, "on_finished"):
                controller.on_finished()
        finally:
            cleanup_fn(controller)
            if on_cleanup:
                on_cleanup()

    worker.finished.connect(_finish_wrapper)

    worker.start()
    return worker


def send_prompt_with_ui_integration(
    controller,
    prompt_config,
    user_input,
    additional_vars=None,
    current_scene_text=None,
    extra_context=None,
    overrides=None,
):
    """Send a prompt to the LLM with full UI integration."""

    if not prompt_config:
        QMessageBox.warning(controller, _("LLM Prompt"), _("Please select a prompt."))
        return False

    final_prompt = prompt_handler.assemble_final_prompt(
        prompt_config, user_input, additional_vars, current_scene_text, extra_context
    )

    preview_text = None
    if hasattr(controller, "right_stack"):
        preview_text = controller.right_stack.preview_text
        preview_text.clear()
        controller.right_stack.send_button.setEnabled(False)
        preview_text.setReadOnly(True)

    QApplication.processEvents()

    def _on_chunk(text):
        if hasattr(controller, "update_text"):
            controller.update_text(text)
        elif preview_text is not None:
            update_llm_text(text, preview_text)

    def _on_finish():
        if hasattr(controller, "on_finished"):
            controller.on_finished()
        elif preview_text is not None:
            handle_llm_completion(controller, preview_text)

    def _on_cleanup():
        if preview_text is not None and hasattr(controller, "right_stack"):
            controller.right_stack.send_button.setEnabled(True)
            preview_text.setReadOnly(False)

    start_llm_stream(
        controller,
        prompt=final_prompt,
        overrides=overrides or {},
        on_chunk=_on_chunk,
        on_finish=_on_finish,
        on_cleanup=_on_cleanup,
    )

    return True


def gather_prompt_data_from_ui(right_stack, scene_editor, project_tree):
    """
    Gather all prompt-related data from UI components.
    Now uses the centralized variable system for cleaner variable management.
    
    Args:
        right_stack: RightStack instance with prompt UI
        scene_editor: SceneEditor instance
        project_tree: ProjectTreeWidget instance
    
    Returns:
        dict: Dictionary containing all gathered prompt data
    """
    if hasattr(right_stack, 'get_prompt_data'):
        return right_stack.get_prompt_data()

    action_beats = right_stack.prompt_input.toPlainText().strip()
    prose_config = right_stack.prose_prompt_panel.get_prompt()
    overrides = right_stack.prose_prompt_panel.get_overrides()

    return {
        'user_input': action_beats,
        'prompt_config': prose_config,
        'overrides': overrides,
        'additional_vars': None,
        'current_scene_text': None,
        'extra_context': None
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
        if hasattr(controller, 'right_stack'):
            controller.right_stack.send_button.setEnabled(True)
            controller.right_stack.preview_text.setReadOnly(False)
        
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
    if hasattr(controller, 'right_stack'):
        controller.right_stack.send_button.setEnabled(True)
        controller.right_stack.preview_text.setReadOnly(False)
    
    raw_text = preview_text_widget.toPlainText()
    if not raw_text.strip():
        QMessageBox.warning(controller, _("LLM Response"), _("The LLM did not return any text. Possible token limit reached or an error occurred."))
        return
    
    # Use the markdown_to_html helper to convert LLM markdown-like output
    try:
        formatted_text = markdown_to_html(raw_text)
        preview_text_widget.setHtml(formatted_text)
    except Exception as e:
        logging.debug(f"markdown_to_html failed: {e}", exc_info=True)
        # Fallback: keep the simple transformation used previously
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

    # Try progressively rendering the accumulated plain text as HTML so the
    # preview shows formatted markdown while streaming. If rendering fails,
    # leave the plain text (this keeps streaming robust).
    try:
        html = markdown_to_html(preview_text_widget.toPlainText())
        preview_text_widget.setHtml(html)
        # Ensure cursor is at the end after replacing with HTML
        cursor = preview_text_widget.textCursor()
        cursor.movePosition(QTextCursor.End)
        preview_text_widget.setTextCursor(cursor)
    except Exception as e:
        logging.debug(f"Progressive markdown_to_html failed: {e}", exc_info=True)


def retry_llm_with_content(controller, prompt_config, user_input, additional_vars, content, extra_context=None):
    """Retry LLM request with different content (e.g., summary instead of full text)."""

    final_prompt = prompt_handler.assemble_final_prompt(
        prompt_config.get("text") if isinstance(prompt_config, dict) else prompt_config,
        user_input,
        additional_vars,
        content,
        extra_context,
    )

    preview_text = getattr(controller.right_stack, "preview_text", None) if hasattr(controller, "right_stack") else None
    if preview_text is not None:
        preview_text.clear()
        preview_text.setReadOnly(True)

    start_llm_stream(
        controller,
        prompt=final_prompt,
        overrides=prompt_config if isinstance(prompt_config, dict) else {},
        on_chunk=(lambda text: update_llm_text(text, preview_text)) if preview_text is not None else None,
        on_finish=(lambda: handle_llm_completion(controller, preview_text)) if preview_text is not None else None,
    )

    if hasattr(controller, "show_token_limit_dialog") and hasattr(controller, "worker") and controller.worker:
        controller.worker.token_limit_exceeded.connect(controller.show_token_limit_dialog)


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
