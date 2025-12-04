/**
 * Manim Studio - Desktop Renderer (PyWebView)
 * Native desktop app using PyWebView API instead of Electron IPC
 */

// App state
let currentFile = null;
let editor = null;
let isAppClosing = false; // Flag to prevent API calls during shutdown

const job = {
    running: false,
    type: null
};

// Terminal history
const terminalHistory = {
    commands: [],
    index: -1,
    maxSize: 50
};

// Auto-save state
let autosaveTimer = null;
let lastSavedCode = '';
let hasUnsavedChanges = false;
const AUTOSAVE_INTERVAL = 30000; // 30 seconds


// Initialize Monaco Editor using AMD require
function initializeEditor() {
    console.log('Initializing Monaco Editor...');

    // Check if AMD require is available
    if (typeof require === 'undefined') {
        console.error('AMD require is not available!');
        return;
    }

    // Use AMD require to load Monaco Editor
    require(['vs/editor/editor.main'], function() {
        console.log('Monaco Editor module loaded');
        console.log('monaco object:', typeof monaco);

        const container = document.getElementById('monacoEditor');
        if (!container) {
            console.error('Monaco editor container not found!');
            return;
        }

        // Ensure container has size
        console.log('Container dimensions:', container.offsetWidth, 'x', container.offsetHeight);

        if (container.offsetWidth === 0 || container.offsetHeight === 0) {
            console.error('Container has zero size! Editor cannot render.');
            return;
        }

        // Default code template
        const defaultCode = `from manim import *

class MyScene(Scene):
    def construct(self):
        # Your animation code here
        text = Text("Hello, Manim!")
        self.play(Write(text))
        self.wait()
`;

        // Create Monaco Editor instance
        editor = monaco.editor.create(container, {
            value: defaultCode,
            language: 'python',
            theme: 'vs-dark',
            fontSize: 14,
            automaticLayout: true,
            readOnly: false,
            minimap: { enabled: true },
            scrollBeyondLastLine: false,
            lineNumbers: 'on',
            roundedSelection: false,
            scrollbar: {
                useShadows: false,
                verticalScrollbarSize: 10,
                horizontalScrollbarSize: 10
            },
            wordWrap: 'on',
            tabSize: 4,
            insertSpaces: true,
            renderWhitespace: 'selection',
            cursorBlinking: 'smooth',
            smoothScrolling: true,
            mouseWheelZoom: true,
            formatOnPaste: true,
            formatOnType: true,
            autoClosingBrackets: 'always',
            autoClosingQuotes: 'always',
            suggestOnTriggerCharacters: true,
            acceptSuggestionOnEnter: 'on',
            quickSuggestions: {
                other: true,
                comments: false,
                strings: false
            },
            // Text selection features
            selectionHighlight: true,               // Highlight text similar to selection
            occurrencesHighlight: true,             // Highlight occurrences of selected text
            selectOnLineNumbers: true,              // Click line numbers to select line
            dragAndDrop: true,                      // Enable drag and drop of text selections
            multiCursorModifier: 'alt',             // Use Alt key for multiple cursors
            renderLineHighlight: 'all',             // Highlight current line and selection
            selectionClipboard: true,               // Copy selection to clipboard on select
            // Enhanced IntelliSense
            suggest: {
                showWords: true,
                showMethods: true,
                showFunctions: true,
                showConstructors: true,
                showFields: true,
                showVariables: true,
                showClasses: true,
                showStructs: true,
                showInterfaces: true,
                showModules: true,
                showProperties: true,
                showEvents: true,
                showOperators: true,
                showUnits: true,
                showValues: true,
                showConstants: true,
                showEnums: true,
                showEnumMembers: true,
                showKeywords: true,
                showSnippets: true
            }
        });

        // Event listeners
        let errorCheckTimeout = null;
        editor.onDidChangeModelContent(() => {
            updateLineCount();
            // Mark as having unsaved changes
            const currentCode = getEditorValue();
            if (currentCode !== lastSavedCode) {
                updateSaveStatus('unsaved');
            }

            // Debounced error checking (wait 500ms after typing stops)
            if (errorCheckTimeout) {
                clearTimeout(errorCheckTimeout);
            }
            errorCheckTimeout = setTimeout(() => {
                checkCodeErrors();
            }, 500);
        });

        editor.onDidChangeCursorPosition(() => {
            updateCursor();
            updateSelection();
        });

        editor.onDidChangeCursorSelection(() => {
            updateSelection();
        });

        // Add keyboard shortcuts for selection
        editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyA, () => {
            // Select all text
            const model = editor.getModel();
            const lastLine = model.getLineCount();
            const lastColumn = model.getLineMaxColumn(lastLine);
            editor.setSelection(new monaco.Selection(1, 1, lastLine, lastColumn));
        });

        // Focus the editor
        setTimeout(() => {
            editor.focus();
        }, 100);

        updateLineCount();
        updateCursor();
        updateSelection();

        console.log('Monaco Editor initialized successfully');
        console.log('Editor is editable:', !editor.getOption(monaco.editor.EditorOption.readOnly));
        console.log('Editor value:', editor.getValue().substring(0, 50) + '...');
    }, function(err) {
        console.error('Failed to load Monaco Editor module:', err);
    });
}

// Helper functions
function getEditorValue() {
    return editor ? editor.getValue() : '';
}

function setEditorValue(value) {
    if (editor) {
        editor.setValue(value);
        updateLineCount();
        updateCursor();
    }
}

function focusEditor() {
    if (editor) editor.focus();
}

function updateLineCount() {
    const lineCount = editor ? editor.getModel().getLineCount() : 0;
    const elem = document.getElementById('linesCount');
    if (elem) elem.textContent = `Lines: ${lineCount}`;
}

function updateCursor() {
    if (!editor) return;
    const position = editor.getPosition();
    const elem = document.getElementById('cursorPosition');
    if (elem) elem.textContent = `Ln ${position.lineNumber}, Col ${position.column}`;
}

function updateSelection() {
    if (!editor) return;

    const selection = editor.getSelection();
    const selectedText = editor.getModel().getValueInRange(selection);

    // Update status bar with selection info
    const elem = document.getElementById('selectionInfo');
    if (elem) {
        if (selectedText && selectedText.length > 0) {
            const lines = selectedText.split('\n').length;
            const chars = selectedText.length;
            elem.textContent = ` (${chars} chars, ${lines} lines selected)`;
            elem.style.display = 'inline';
        } else {
            elem.textContent = '';
            elem.style.display = 'none';
        }
    }
}

function getSelectedText() {
    if (!editor) return '';
    const selection = editor.getSelection();
    return editor.getModel().getValueInRange(selection);
}

function updateCurrentFile(filename) {
    const elem = document.getElementById('currentFile');
    if (elem) {
        elem.textContent = filename || 'Untitled';
        elem.title = currentFile || '';
    }
}

function toast(message, type = 'info') {
    console.log(`[${type.toUpperCase()}] ${message}`);

    // Get or create toast container
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        document.body.appendChild(container);
    }

    // Icon mapping
    const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ'
    };

    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    // Create icon
    const icon = document.createElement('div');
    icon.className = 'toast-icon';
    icon.textContent = icons[type] || icons.info;

    // Create message
    const messageEl = document.createElement('div');
    messageEl.className = 'toast-message';
    messageEl.textContent = message;

    // Create progress bar
    const progress = document.createElement('div');
    progress.className = 'toast-progress';

    // Assemble toast
    toast.appendChild(icon);
    toast.appendChild(messageEl);
    toast.appendChild(progress);

    // Add to container
    container.appendChild(toast);

    // Trigger show animation
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);

    // Auto-dismiss after 3 seconds
    const dismissTimeout = setTimeout(() => {
        toast.classList.add('hiding');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 3000);

    // Pause on hover
    toast.addEventListener('mouseenter', () => {
        clearTimeout(dismissTimeout);
        progress.style.animationPlayState = 'paused';
    });

    toast.addEventListener('mouseleave', () => {
        progress.style.animationPlayState = 'running';
        setTimeout(() => {
            toast.classList.add('hiding');
            setTimeout(() => {
                toast.remove();
            }, 300);
        }, 1000);
    });
}

// Console functions (for xterm.js terminal)
function appendConsole(text, type = 'info') {
    // Write to xterm.js terminal if available
    if (term) {
        // Add color based on type
        let color = '';
        if (type === 'error') {
            color = '\x1b[31m'; // Red
        } else if (type === 'success') {
            color = '\x1b[32m'; // Green
        } else if (type === 'warning') {
            color = '\x1b[33m'; // Yellow
        }
        const reset = color ? '\x1b[0m' : '';
        term.write(color + text + reset + '\r\n');
    } else {
        // Fallback to console.log
        console.log(`[CONSOLE ${type.toUpperCase()}]`, text);
    }
}

function clearConsole() {
    if (term) {
        term.clear();
    } else {
        console.log('[CONSOLE] Clear requested but terminal not available');
    }
}

function setTerminalStatus(text, type = 'info') {
    const status = document.getElementById('terminalStatus');
    if (status) {
        status.textContent = text;
        status.className = `terminal-status status-${type}`;
    }
}

function focusInput() {
    // Focus xterm.js terminal if available
    if (term) {
        term.focus();
    }
}

// File operations
async function newFile() {
    try {
        const res = await pywebview.api.new_file();
        if (res.status === 'success') {
            setEditorValue(res.code);
            currentFile = null;
            updateCurrentFile('Untitled');
            toast('New file created', 'success');
            focusEditor();
        }
    } catch (err) {
        toast(`Error: ${err.message}`, 'error');
    }
}

async function openFile() {
    try {
        const res = await pywebview.api.open_file_dialog();
        if (res.status === 'success') {
            setEditorValue(res.code);
            currentFile = res.path;
            updateCurrentFile(res.filename);
            updateLineCount();
            updateCursor();
            focusEditor();
            toast(`Opened ${res.filename}`, 'success');
        }
    } catch (err) {
        toast(`Open failed: ${err.message}`, 'error');
    }
}

async function saveFile() {
    try {
        const code = getEditorValue();
        const res = await pywebview.api.save_file(code, currentFile);

        if (res.status === 'success') {
            currentFile = res.path;
            updateCurrentFile(res.filename);
            toast('File saved', 'success');
            // Update save status
            lastSavedCode = code;
            updateSaveStatus('saved');
        }
    } catch (err) {
        toast(`Save failed: ${err.message}`, 'error');
    }
}

async function saveFileAs() {
    try {
        const code = getEditorValue();
        const res = await pywebview.api.save_file_dialog(code);

        if (res.status === 'success') {
            currentFile = res.path;
            updateCurrentFile(res.filename);
            toast('File saved', 'success');
            // Update save status
            lastSavedCode = code;
            updateSaveStatus('saved');
        }
    } catch (err) {
        toast(`Save failed: ${err.message}`, 'error');
    }
}

// Auto-save functions
function updateSaveStatus(status) {
    const indicator = document.getElementById('autosaveIndicator');
    const statusText = document.getElementById('autosaveStatus');
    const icon = indicator.querySelector('i');

    // Remove all status classes
    indicator.classList.remove('saved', 'saving', 'unsaved');

    if (status === 'saved') {
        indicator.classList.add('saved');
        icon.className = 'fas fa-check-circle';
        statusText.textContent = 'Saved';
        hasUnsavedChanges = false;
    } else if (status === 'saving') {
        indicator.classList.add('saving');
        icon.className = 'fas fa-spinner';
        statusText.textContent = 'Saving...';
    } else if (status === 'unsaved') {
        indicator.classList.add('unsaved');
        icon.className = 'fas fa-exclamation-circle';
        statusText.textContent = 'Unsaved changes';
        hasUnsavedChanges = true;
    }
}

async function performAutosave() {
    if (!editor || isAppClosing) return;

    const code = getEditorValue();

    // Don't autosave if code hasn't changed
    if (code === lastSavedCode) {
        return;
    }

    // Don't autosave empty code
    if (!code.trim()) {
        return;
    }

    try {
        updateSaveStatus('saving');
        const result = await pywebview.api.autosave_code(code);

        if (result.status === 'success') {
            console.log('[AUTOSAVE] Auto-saved successfully:', result.timestamp);
            updateSaveStatus('saved');
            lastSavedCode = code;
        } else {
            console.error('[AUTOSAVE] Failed:', result.message);
            updateSaveStatus('unsaved');
        }
    } catch (err) {
        console.error('[AUTOSAVE] Error:', err);
        updateSaveStatus('unsaved');
    }
}

function startAutosave() {
    console.log('[AUTOSAVE] Starting auto-save timer (30 seconds)');

    // Clear existing timer
    if (autosaveTimer) {
        clearInterval(autosaveTimer);
    }

    // Start new timer
    autosaveTimer = setInterval(() => {
        performAutosave();
    }, AUTOSAVE_INTERVAL);
}

function stopAutosave() {
    console.log('[AUTOSAVE] Stopping auto-save timer');
    if (autosaveTimer) {
        clearInterval(autosaveTimer);
        autosaveTimer = null;
    }
}

async function checkForAutosaves() {
    try {
        const result = await pywebview.api.get_autosave_files();

        if (result.status === 'success' && result.files.length > 0) {
            showAutosaveRecoveryDialog(result.files);
        }
    } catch (err) {
        console.error('[AUTOSAVE] Error checking for autosaves:', err);
    }
}

function showAutosaveRecoveryDialog(autosaves) {
    // Get the most recent autosave
    const latest = autosaves[0];

    const modal = document.createElement('div');
    modal.className = 'modal-overlay active';
    modal.style.zIndex = '10000';

    modal.innerHTML = `
        <div class="modal-container" style="max-width: 500px;">
            <div class="modal-header">
                <h2>
                    <i class="fas fa-history"></i>
                    Recover Unsaved Work?
                </h2>
            </div>
            <div class="modal-body">
                <p style="margin: 0 0 16px 0; color: var(--text-secondary);">
                    An auto-saved version of your work was found. Would you like to recover it?
                </p>
                <div style="padding: 12px; background: var(--bg-secondary); border-radius: 6px; margin-bottom: 16px;">
                    <strong style="color: var(--text-primary);">Auto-saved:</strong>
                    <span style="color: var(--text-secondary); margin-left: 8px;">${formatTimestamp(latest.timestamp)}</span>
                    <br>
                    <strong style="color: var(--text-primary);">File:</strong>
                    <span style="color: var(--text-secondary); margin-left: 8px;">${latest.file_path || 'Untitled'}</span>
                </div>
                <p style="margin: 0; font-size: 13px; color: var(--text-secondary);">
                    <i class="fas fa-info-circle"></i> Found ${autosaves.length} auto-save(s)
                </p>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" id="discardAutosaveBtn">Discard</button>
                <button class="btn btn-primary" id="recoverAutosaveBtn">
                    <i class="fas fa-undo"></i> Recover
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Handle recover button
    document.getElementById('recoverAutosaveBtn').addEventListener('click', async () => {
        try {
            const result = await pywebview.api.load_autosave(latest.autosave_file);
            if (result.status === 'success') {
                setEditorValue(result.code);
                lastSavedCode = result.code;
                toast('Work recovered successfully', 'success');
                modal.remove();
            } else {
                toast('Failed to recover work', 'error');
            }
        } catch (err) {
            toast(`Recovery failed: ${err.message}`, 'error');
        }
    });

    // Handle discard button
    document.getElementById('discardAutosaveBtn').addEventListener('click', async () => {
        try {
            // Delete all autosaves
            for (const autosave of autosaves) {
                await pywebview.api.delete_autosave(autosave.autosave_file);
            }
            toast('Auto-saves discarded', 'info');
            modal.remove();
        } catch (err) {
            console.error('[AUTOSAVE] Error discarding:', err);
            modal.remove();
        }
    });
}

function formatTimestamp(timestamp) {
    // Format: YYYYMMDD_HHMMSS -> readable format
    const year = timestamp.substring(0, 4);
    const month = timestamp.substring(4, 6);
    const day = timestamp.substring(6, 8);
    const hour = timestamp.substring(9, 11);
    const minute = timestamp.substring(11, 13);
    const second = timestamp.substring(13, 15);

    return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
}

// Code Error Checking Functions
let currentErrorDecorations = [];

async function checkCodeErrors() {
    if (!editor || !pywebview?.api) {
        console.log('[ERROR CHECK] Editor or API not ready');
        return;
    }

    const code = getEditorValue();
    console.log('[ERROR CHECK] Checking code, length:', code.length);

    try {
        const result = await pywebview.api.check_code_errors(code);
        console.log('[ERROR CHECK] Result:', result);

        if (result.status === 'success') {
            displayErrors(result.errors);
        }
    } catch (err) {
        console.error('[ERROR CHECK] Failed:', err);
    }
}

function displayErrors(errors) {
    const errorsList = document.getElementById('errorsList');
    const errorCount = document.getElementById('errorCount');
    const errorsPanel = document.getElementById('codeErrorsPanel');
    const monacoEditor = document.getElementById('monacoEditor');

    console.log('[ERROR DISPLAY] Displaying errors:', errors);

    if (!errorsList || !errorCount || !errorsPanel || !monacoEditor) {
        console.error('[ERROR DISPLAY] Error elements not found!');
        return;
    }

    if (!errors || errors.length === 0) {
        // No errors - hide panel and expand editor to full height
        errorsPanel.style.display = 'none';
        monacoEditor.style.height = '100%';

        // Clear Monaco decorations
        if (editor) {
            currentErrorDecorations = editor.deltaDecorations(currentErrorDecorations, []);
            editor.layout(); // Trigger layout recalculation
        }
        return;
    }

    // Errors found - show panel and adjust editor height
    errorsPanel.style.display = 'block';
    monacoEditor.style.height = 'calc(100% - 120px)';

    // Display errors
    errorCount.textContent = errors.length;
    errorsList.innerHTML = '';

    const decorations = [];

    errors.forEach((error, index) => {
        const errorItem = document.createElement('div');
        errorItem.className = `error-item ${error.type === 'warning' ? 'warning' : ''}`;

        errorItem.innerHTML = `
            <i class="fas ${error.type === 'warning' ? 'fa-exclamation-triangle' : 'fa-times-circle'} error-icon"></i>
            <div class="error-content">
                <div class="error-location">Line ${error.line}${error.column ? `, Column ${error.column}` : ''}</div>
                <div class="error-message">${escapeHtml(error.message)}</div>
            </div>
        `;

        // Click to jump to error line
        errorItem.addEventListener('click', () => {
            if (editor && error.line > 0) {
                editor.revealLineInCenter(error.line);
                editor.setPosition({ lineNumber: error.line, column: error.column || 1 });
                editor.focus();
            }
        });

        errorsList.appendChild(errorItem);

        // Add Monaco decoration for error line
        if (error.line > 0) {
            decorations.push({
                range: new monaco.Range(error.line, 1, error.line, 1),
                options: {
                    isWholeLine: true,
                    className: error.type === 'warning' ? 'warningLine' : 'errorLine',
                    glyphMarginClassName: error.type === 'warning' ? 'warningGlyph' : 'errorGlyph',
                    glyphMarginHoverMessage: { value: error.message }
                }
            });
        }
    });

    // Apply decorations to editor
    if (editor && decorations.length > 0) {
        currentErrorDecorations = editor.deltaDecorations(currentErrorDecorations, decorations);
    }

    // Trigger layout recalculation after showing panel
    if (editor) {
        editor.layout();
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function clearErrors() {
    const errorsPanel = document.getElementById('codeErrorsPanel');
    const monacoEditor = document.getElementById('monacoEditor');

    // Hide panel and expand editor to full height
    if (errorsPanel) {
        errorsPanel.style.display = 'none';
    }
    if (monacoEditor) {
        monacoEditor.style.height = '100%';
    }

    // Clear Monaco decorations
    if (editor) {
        currentErrorDecorations = editor.deltaDecorations(currentErrorDecorations, []);
        editor.layout(); // Trigger layout recalculation
    }
}

// Rendering functions
async function renderAnimation() {
    if (job.running) {
        toast('Another job is running', 'warning');
        return;
    }

    let quality = document.getElementById('qualitySelect').value;
    let fps = document.getElementById('fpsSelect').value;

    // Handle custom resolution
    if (quality === 'custom') {
        const width = parseInt(document.getElementById('customWidth').value, 10) || 1920;
        const height = parseInt(document.getElementById('customHeight').value, 10) || 1080;
        quality = `${width}x${height}`;
    }

    // Handle custom FPS
    if (fps === 'custom') {
        fps = parseInt(document.getElementById('customFps').value, 10) || 30;
    } else {
        fps = parseInt(fps, 10) || 30;
    }

    const code = getEditorValue();

    if (!code.trim()) {
        toast('No code to render', 'warning');
        return;
    }

    // Just run the command in terminal - no UI messages
    try {
        const res = await pywebview.api.render_animation(code, quality, fps);

        if (res.status === 'error') {
            toast(`Render failed: ${res.message}`, 'error');
        }
    } catch (err) {
        toast(`Render error: ${err.message}`, 'error');
    }
}

async function quickPreview() {
    if (job.running) {
        toast('Another job is running', 'warning');
        return;
    }

    let quality = document.getElementById('previewQualitySelect').value;
    let fps = document.getElementById('previewFpsSelect').value;

    // Handle custom resolution
    if (quality === 'custom') {
        const width = parseInt(document.getElementById('previewCustomWidth').value, 10) || 1920;
        const height = parseInt(document.getElementById('previewCustomHeight').value, 10) || 1080;
        quality = `${width}x${height}`;
    }

    // Handle custom FPS
    if (fps === 'custom') {
        fps = parseInt(document.getElementById('previewCustomFps').value, 10) || 15;
    } else {
        fps = parseInt(fps, 10) || 15;
    }

    const code = getEditorValue();

    if (!code.trim()) {
        toast('No code to preview', 'warning');
        return;
    }

    // Just run the command in terminal - no UI messages
    try {
        const res = await pywebview.api.quick_preview(code, quality, fps);

        if (res.status === 'error') {
            toast(`Preview failed: ${res.message}`, 'error');
        }
    } catch (err) {
        toast(`Preview error: ${err.message}`, 'error');
        job.running = false;
        setTerminalStatus('Error', 'error');
    }
}

async function stopActiveRender() {
    if (!job.running) {
        toast('No render in progress', 'info');
        return;
    }

    setTerminalStatus('Stopping...', 'warning');

    try {
        const res = await pywebview.api.stop_render();

        if (res.status === 'success') {
            appendConsole('Render stopped', 'info');
            job.running = false;
            setTerminalStatus('Stopped', 'info');
        } else {
            appendConsole(`Stop failed: ${res.message}`, 'error');
        }
    } catch (err) {
        appendConsole(`Stop error: ${err.message}`, 'error');
    }
}

// Callbacks for render updates (called by Python)
window.updateRenderOutput = function(line) {
    appendConsole(line);
};

// Function to display media in preview panel - OPTIMIZED
async function showPreview(filePath) {
    console.log('[PREVIEW] showPreview called with path:', filePath);

    const previewVideo = document.getElementById('previewVideo');
    const previewImage = document.getElementById('previewImage');
    const placeholder = document.querySelector('.preview-placeholder');
    const filenameSpan = document.getElementById('previewFilename');

    if (!filePath) {
        if (placeholder) placeholder.style.display = 'flex';
        previewVideo.style.display = 'none';
        previewImage.style.display = 'none';
        return;
    }

    // IMPORTANT: Properly clear and unload old video to force complete reload
    console.log('[PREVIEW] Clearing old preview sources...');

    // Step 1: Pause current video
    previewVideo.pause();

    // Step 2: Remove src attribute completely (not just empty string)
    previewVideo.removeAttribute('src');

    // Step 3: Remove all child source elements if any
    while (previewVideo.firstChild) {
        previewVideo.removeChild(previewVideo.firstChild);
    }

    // Step 4: Trigger load to clear buffer
    previewVideo.load();

    // Clear image too
    previewImage.removeAttribute('src');

    // Hide all first
    previewVideo.style.display = 'none';
    previewImage.style.display = 'none';
    if (placeholder) placeholder.style.display = 'none';

    // Get filename and extension
    const filename = filePath.split(/[/\\]/).pop();
    const ext = filename.split('.').pop().toLowerCase();
    filenameSpan.textContent = filename;

    console.log('[PREVIEW] Loading NEW preview from assets folder:', filename);
    console.log('[PREVIEW] File type:', ext);

    try {
        // Convert assets folder path to HTTP URL for display
        console.log('[PREVIEW] Requesting HTTP URL from backend...');
        const result = await pywebview.api.get_asset_as_data_url(filePath);

        console.log('[PREVIEW] Backend response:', result.status);

        if (result.status !== 'success' || !result.dataUrl) {
            filenameSpan.textContent = `Error: ${result.message || 'Failed to load'}`;
            if (placeholder) placeholder.style.display = 'flex';
            return;
        }

        // Video formats
        if (ext === 'mp4' || ext === 'mov' || ext === 'webm' || ext === 'avi') {
            console.log('[PREVIEW] Displaying NEW video with HTTP URL:', result.dataUrl.substring(0, 50) + '...');

            // Set up event handlers before setting src
            previewVideo.onerror = () => {
                console.error('[PREVIEW] Error loading video:', filename);
                filenameSpan.textContent = `Error loading ${filename}`;
            };

            previewVideo.onloadeddata = () => {
                console.log('[PREVIEW] ✅ NEW video loaded successfully:', filename);
            };

            // Add cache-busting parameter to force reload
            const cacheBuster = Date.now();
            const videoUrl = result.dataUrl.includes('?')
                ? `${result.dataUrl}&_=${cacheBuster}`
                : `${result.dataUrl}?_=${cacheBuster}`;

            console.log('[PREVIEW] Setting NEW video source with cache buster:', cacheBuster);

            // Set src attribute (not using setAttribute to ensure proper handling)
            previewVideo.src = videoUrl;

            // Show video element
            previewVideo.style.display = 'block';

            // Trigger load() to load the new source
            previewVideo.load();

            // Attempt autoplay
            previewVideo.play().catch(() => {
                console.log('[PREVIEW] Autoplay prevented (user interaction required)');
            });

            console.log('[PREVIEW] ✅ Preview box updated with new video');
        }
        // Image formats
        else if (ext === 'png' || ext === 'jpg' || ext === 'jpeg' || ext === 'gif' || ext === 'webp') {
            console.log('[PREVIEW] Displaying NEW image with HTTP URL:', result.dataUrl.substring(0, 50) + '...');

            // Set up event handlers before setting src
            previewImage.onload = () => {
                console.log('[PREVIEW] ✅ NEW image loaded successfully:', filename);
                filenameSpan.textContent = filename;
            };

            previewImage.onerror = () => {
                console.error('[PREVIEW] Error loading image:', filename);
                filenameSpan.textContent = `Error loading ${filename}`;
            };

            // Add cache-busting parameter to force reload
            const cacheBuster = Date.now();
            const imageUrl = result.dataUrl.includes('?')
                ? `${result.dataUrl}&_=${cacheBuster}`
                : `${result.dataUrl}?_=${cacheBuster}`;

            console.log('[PREVIEW] Setting NEW image source with cache buster:', cacheBuster);

            // Set new src
            previewImage.src = imageUrl;

            // Show image element
            previewImage.style.display = 'block';

            console.log('[PREVIEW] ✅ Preview box updated with new image');
        }
        else {
            filenameSpan.textContent = `Unsupported: ${ext}`;
            if (placeholder) placeholder.style.display = 'flex';
        }

    } catch (error) {
        filenameSpan.textContent = `Error: ${error.message}`;
        if (placeholder) placeholder.style.display = 'flex';
    }
}

// Save rendered file from assets to user's chosen location
async function saveRenderedFile(sourcePath, suggestedName) {
    console.log('[SAVE] Calling save_rendered_file...');
    console.log('   Source:', sourcePath);
    console.log('   Suggested name:', suggestedName);

    try {
        const result = await pywebview.api.save_rendered_file(sourcePath, suggestedName);

        if (result.status === 'success') {
            console.log('[SAVE] File saved successfully!');
            console.log('   Saved to:', result.path);
            toast('File saved successfully!', 'success');
            // Only refresh assets if the file was from assets folder, not render folder
            // (render folder is already cleared after save)
            if (!sourcePath.includes('render')) {
                refreshAssets();
            }
        } else if (result.status === 'cancelled') {
            console.log('[SAVE] User cancelled save dialog');
            toast('Save cancelled', 'info');
        } else {
            console.error('[SAVE] Save failed:', result.message);
            toast(`Save failed: ${result.message}`, 'error');
        }
    } catch (error) {
        console.error('[SAVE] Error calling save_rendered_file:', error);
        toast('Error saving file', 'error');
    }
}

// Show save dialog for completed render
window.showRenderSaveDialog = function(renderFilePath) {
    console.log('💾 Showing save dialog for render:', renderFilePath);

    // Extract filename from path for suggested name
    const pathParts = renderFilePath.split(/[\\\/]/);
    const filename = pathParts[pathParts.length - 1];

    // Show save dialog
    saveRenderedFile(renderFilePath, filename);
};

// Modified to accept autoSave parameter and trigger save dialog automatically
window.renderCompleted = function(outputPath, autoSave = false, suggestedName = 'MyScene.mp4') {
    console.log('🎉 Render completed!');
    console.log('📂 Output path received:', outputPath);
    console.log('📂 AutoSave:', autoSave);
    console.log('📂 Suggested name:', suggestedName);

    appendConsole('─'.repeat(60), 'info');
    appendConsole('✓ Render completed successfully!', 'success');
    appendConsole('─'.repeat(60), 'info');
    job.running = false;
    setTerminalStatus('Ready', 'success');
    toast('Render completed!', 'success');

    // Auto-show in main preview box and switch to workspace tab
    if (outputPath) {
        console.log('🎬 Auto-loading preview...');
        showPreview(outputPath);

        // Auto-switch to workspace tab to show the preview
        const workspaceTab = document.querySelector('.tab-pill[data-tab="workspace"]');
        if (workspaceTab) {
            console.log('🔄 Switching to workspace tab...');
            workspaceTab.click();
        }

        // If autoSave is enabled, show save dialog after a short delay
        if (autoSave) {
            console.log('[AUTO-SAVE] Will show save dialog in 500ms...');
            setTimeout(() => {
                console.log('[AUTO-SAVE] Showing save dialog now...');
                saveRenderedFile(outputPath, suggestedName);
            }, 500);
        }
    } else {
        console.warn('⚠️ No output path provided to renderCompleted');
    }
};

window.renderFailed = function(error) {
    appendConsole('─'.repeat(60), 'info');
    appendConsole(`✗ Render failed: ${error}`, 'error');
    appendConsole('─'.repeat(60), 'info');
    job.running = false;
    setTerminalStatus('Error', 'error');
};

window.previewCompleted = function(outputPath) {
    console.log('🎉 Preview completed!');
    console.log('📂 Output path received:', outputPath);
    console.log('📁 File is now in assets folder for display');

    appendConsole('─'.repeat(60), 'info');
    appendConsole('✓ Preview completed! File ready in preview box.', 'success');
    appendConsole('─'.repeat(60), 'info');
    job.running = false;
    setTerminalStatus('Ready', 'success');

    // Auto-show in main preview box and switch to workspace tab
    if (outputPath) {
        console.log('🎬 Auto-loading preview from assets folder...');
        console.log('   Path:', outputPath);

        // Load preview using get_asset_as_data_url for HTTP URL
        showPreview(outputPath);

        // Auto-switch to workspace tab to show the preview
        const workspaceTab = document.querySelector('.tab-pill[data-tab="workspace"]');
        if (workspaceTab) {
            console.log('🔄 Switching to workspace tab to show preview...');
            workspaceTab.click();
        }

        console.log('✅ Preview loaded in preview box (will auto-delete on app close)');
    } else {
        console.warn('⚠️ No output path provided to previewCompleted');
        appendConsole('Warning: No preview file found', 'warning');
    }
};

window.previewFailed = function(error) {
    appendConsole('─'.repeat(60), 'info');
    appendConsole(`✗ Preview failed: ${error}`, 'error');
    appendConsole('─'.repeat(60), 'info');
    job.running = false;
    setTerminalStatus('Error', 'error');
};

// CACHE BUSTER - Version 2025-01-25-v9
// ASSETS WORKFLOW: Render → Move to assets → Auto-save dialog → User chooses location
console.log('[RENDERER] Loaded renderer_desktop.js - Version 2025-01-25-v9 - ASSETS WORKFLOW');
console.log('[RENDERER] ✅ Render: Move to assets → Auto-save dialog → User saves to location');

// Assets management
// Helper function to get file type icon
function getFileTypeIcon(fileName) {
    const ext = fileName.split('.').pop().toLowerCase();
    const iconMap = {
        'mp4': 'fa-file-video',
        'mov': 'fa-file-video',
        'webm': 'fa-file-video',
        'avi': 'fa-file-video',
        'png': 'fa-file-image',
        'jpg': 'fa-file-image',
        'jpeg': 'fa-file-image',
        'gif': 'fa-file-image',
        'svg': 'fa-file-image'
    };
    return iconMap[ext] || 'fa-file';
}

// Helper function to get file type badge
function getFileTypeBadge(fileName) {
    const ext = fileName.split('.').pop().toLowerCase();
    if (['mp4', 'mov', 'webm', 'avi'].includes(ext)) {
        return { text: 'VIDEO', class: 'video' };
    } else if (['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(ext)) {
        return { text: 'IMAGE', class: 'image' };
    }
    return { text: ext.toUpperCase(), class: '' };
}

// Helper function to format date
function formatDate(timestamp) {
    if (!timestamp) return 'Unknown';
    const date = new Date(timestamp * 1000);
    const now = new Date();
    const diffTime = Math.abs(now - date);
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
        return 'Today';
    } else if (diffDays === 1) {
        return 'Yesterday';
    } else if (diffDays < 7) {
        return `${diffDays} days ago`;
    } else {
        return date.toLocaleDateString();
    }
}

// Global state for assets
let allAssets = [];
let currentFilter = 'all';
let searchQuery = '';
let currentAsset = null; // Currently selected asset for modal

async function refreshAssets() {
    console.log('============================================');
    console.log('📦 REFRESHING ASSETS...');
    console.log('============================================');

    try {
        console.log('[ASSETS] Checking pywebview API...');
        if (typeof pywebview === 'undefined' || !pywebview.api) {
            console.error('[ASSETS] ✗ PyWebView API not available!');
            return;
        }
        console.log('[ASSETS] ✓ PyWebView API available');

        console.log('[ASSETS] Calling list_media_files()...');
        const res = await pywebview.api.list_media_files();
        console.log('[ASSETS] Response:', res);

        if (!res.files || res.files.length === 0) {
            console.log('[ASSETS] No files found');
            allAssets = [];
            displayAssets([]);
            return;
        }

        allAssets = res.files;
        console.log(`[ASSETS] ✅ Found ${allAssets.length} assets:`, allAssets.map(f => f.name));
        console.log('[ASSETS] About to call displayAssets() with', allAssets.length, 'files');
        console.log('[ASSETS] allAssets array:', allAssets);
        displayAssets(allAssets);
        console.log('[ASSETS] displayAssets() call completed');
    } catch (err) {
        console.error('[ASSETS] ❌ Failed to refresh assets:', err);
        console.error('[ASSETS] Error stack:', err.stack);
    }
}

// COMPLETELY REWRITTEN displayAssets() - Using pure innerHTML for better compatibility
function displayAssets(files) {
    try {
        console.log('============================================');
        console.log('[ASSETS] displayAssets() START');
        console.log('[ASSETS] Files parameter:', files);
        console.log('[ASSETS] Files type:', typeof files);
        console.log('[ASSETS] Files is array?', Array.isArray(files));
        console.log('[ASSETS] Files length:', files ? files.length : 'null/undefined');
        console.log('============================================');

        const container = document.getElementById('assetsGrid');

        if (!container) {
            console.error('[ASSETS] ❌ CRITICAL: assetsGrid element not found!');
            alert('ERROR: Assets container not found in DOM!');
            return;
        }

        console.log('[ASSETS] ✓ Container found, ID:', container.id);
        console.log('[ASSETS] Container display style:', window.getComputedStyle(container).display);
        console.log('[ASSETS] Container visibility:', window.getComputedStyle(container).visibility);

        // Empty state
        if (!files || files.length === 0) {
            console.log('[ASSETS] No files - showing empty state');
            container.innerHTML = `
                <div class="empty-state" style="padding: 40px; text-align: center;">
                    <i class="fas fa-box-open" style="font-size: 48px; color: #666; margin-bottom: 16px;"></i>
                    <p style="color: #999; font-size: 16px;">No assets yet. Render something!</p>
                </div>
            `;
            updateAssetsCount(0);
            return;
        }

        // Apply filters
        let filteredFiles = files;

        if (searchQuery) {
            filteredFiles = filteredFiles.filter(file =>
                file.name.toLowerCase().includes(searchQuery.toLowerCase())
            );
        }

        if (currentFilter !== 'all') {
            filteredFiles = filteredFiles.filter(file => {
                const ext = file.name.split('.').pop().toLowerCase();
                if (currentFilter === 'video') {
                    return ['mp4', 'mov', 'webm', 'avi'].includes(ext);
                } else if (currentFilter === 'image') {
                    return ['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(ext);
                }
                return true;
            });
        }

        if (filteredFiles.length === 0) {
            console.log('[ASSETS] No files match filters');
            container.innerHTML = `
                <div class="empty-state" style="padding: 40px; text-align: center;">
                    <i class="fas fa-filter" style="font-size: 48px; color: #666; margin-bottom: 16px;"></i>
                    <p style="color: #999; font-size: 16px;">No assets match your filters</p>
                </div>
            `;
            updateAssetsCount(0);
            return;
        }

        updateAssetsCount(filteredFiles.length);

        // Build HTML string for ALL assets at once
        console.log('[ASSETS] Building HTML for', filteredFiles.length, 'files...');
        let assetsHTML = '';

        filteredFiles.forEach((file, index) => {
            console.log(`[ASSETS] [${index + 1}/${filteredFiles.length}] ${file.name}`);

            const ext = file.name.split('.').pop().toLowerCase();
            const isVideo = ['mp4', 'mov', 'webm', 'avi'].includes(ext);
            const isImage = ['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(ext);

            const badge = getFileTypeBadge(file.name);
            const icon = getFileTypeIcon(file.name);

            // Convert Windows path to web path
            const webPath = file.path.replace(/\\/g, '/');

            // Build thumbnail
            let thumbnailHTML = '';
            if (isVideo) {
                thumbnailHTML = `<video src="${webPath}" muted style="width: 100%; height: 100%; object-fit: cover;"></video>`;
            } else if (isImage) {
                thumbnailHTML = `<img src="${webPath}" alt="${file.name}" style="width: 100%; height: 100%; object-fit: cover;">`;
            } else {
                thumbnailHTML = `<i class="fas ${icon}" style="font-size: 48px; color: var(--accent-primary);"></i>`;
            }

            // Build complete asset card HTML
            assetsHTML += `
            <div class="asset-item" onclick="openAssetByIndex(${index})" style="
                background: var(--bg-secondary);
                border: 1px solid var(--border-color);
                border-radius: 8px;
                padding: 12px;
                cursor: pointer;
                transition: all 0.2s ease;
            " onmouseover="this.style.borderColor='var(--accent-primary)'" onmouseout="this.style.borderColor='var(--border-color)'">
                <div class="asset-thumbnail" style="
                    width: 100%;
                    height: 150px;
                    background: var(--bg-primary);
                    border-radius: 6px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    overflow: hidden;
                    margin-bottom: 12px;
                ">
                    ${thumbnailHTML}
                </div>
                <div class="asset-info">
                    <div class="asset-name" title="${file.name}" style="
                        font-weight: 500;
                        color: var(--text-primary);
                        margin-bottom: 8px;
                        overflow: hidden;
                        text-overflow: ellipsis;
                        white-space: nowrap;
                    ">${file.name}</div>
                    <div class="asset-meta" style="
                        display: flex;
                        flex-wrap: wrap;
                        gap: 8px;
                        font-size: 12px;
                        color: var(--text-secondary);
                    ">
                        <span class="asset-type-badge ${badge.class}" style="
                            background: var(--accent-primary);
                            color: white;
                            padding: 2px 8px;
                            border-radius: 4px;
                            font-weight: 500;
                        ">${badge.text}</span>
                        <span class="asset-size">
                            <i class="fas fa-hdd"></i> ${formatBytes(file.size)}
                        </span>
                        <span class="asset-date">
                            <i class="fas fa-clock"></i> ${formatDate(file.mtime)}
                        </span>
                    </div>
                </div>
            </div>
        `;
        });

        // Set ALL HTML at once (much faster and more reliable than appendChild)
        console.log('[ASSETS] Setting container innerHTML...');
        console.log('[ASSETS] HTML length:', assetsHTML.length, 'characters');
        container.innerHTML = assetsHTML;

        console.log('[ASSETS] ============================================');
        console.log('[ASSETS] ✅ COMPLETE - Displayed', filteredFiles.length, 'assets');
        console.log('[ASSETS] Container children:', container.children.length);
        console.log('[ASSETS] Container innerHTML length:', container.innerHTML.length);
        console.log('[ASSETS] First child element:', container.firstChild);
        console.log('[ASSETS] ============================================');

    } catch (error) {
        console.error('[ASSETS] ❌❌❌ EXCEPTION IN displayAssets():', error);
        console.error('[ASSETS] Error message:', error.message);
        console.error('[ASSETS] Error stack:', error.stack);
        alert(`CRITICAL ERROR in displayAssets(): ${error.message}`);
    }
}

// Helper function to open asset by index (since we're using inline onclick)
window.openAssetByIndex = function(index) {
    const file = allAssets[index];
    if (file) {
        console.log('📺 Asset clicked:', file.name);
        openAssetModal(file);
    }
};

// Open asset preview modal
function openAssetModal(file) {
    currentAsset = file;
    const modal = document.getElementById('assetPreviewModal');
    const video = document.getElementById('assetModalVideo');
    const image = document.getElementById('assetModalImage');

    // Hide both
    video.style.display = 'none';
    image.style.display = 'none';

    // Convert path to file:// URL
    let webPath = file.path.replace(/\\/g, '/');
    if (!webPath.startsWith('file://') && !webPath.startsWith('http')) {
        webPath = 'file:///' + webPath;
    }

    const ext = file.name.split('.').pop().toLowerCase();

    // Show appropriate media
    if (ext === 'mp4' || ext === 'mov' || ext === 'webm') {
        video.src = webPath;
        video.style.display = 'block';
        video.load();
    } else if (ext === 'png' || ext === 'jpg' || ext === 'jpeg' || ext === 'gif') {
        image.src = webPath;
        image.style.display = 'block';
    }

    // Set details
    document.getElementById('assetDetailName').textContent = file.name;
    document.getElementById('assetDetailSize').textContent = formatBytes(file.size);
    document.getElementById('assetDetailType').textContent = ext.toUpperCase();
    document.getElementById('assetDetailDate').textContent = formatDate(file.mtime);
    document.getElementById('assetDetailPath').textContent = file.path;

    // Show modal
    modal.style.display = 'flex';
}

// Close asset modal
function closeAssetModal() {
    const modal = document.getElementById('assetPreviewModal');
    const video = document.getElementById('assetModalVideo');

    // Stop video if playing
    if (video) {
        video.pause();
        video.src = '';
    }

    modal.style.display = 'none';
    currentAsset = null;
}

// Open asset in main preview box
function openInMainPreview() {
    if (currentAsset) {
        // Close modal
        closeAssetModal();

        // Show in main preview
        showPreview(currentAsset.path);

        // Switch to workspace tab
        const workspaceTab = document.querySelector('.tab-pill[data-tab="workspace"]');
        if (workspaceTab) workspaceTab.click();
    }
}

// Update assets count display
function updateAssetsCount(count) {
    const countElement = document.getElementById('assetsCount');
    if (countElement) {
        countElement.textContent = `${count} ${count === 1 ? 'item' : 'items'}`;
    }
}

// Setup assets search
function setupAssetsSearch() {
    const searchInput = document.getElementById('assetsSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            searchQuery = e.target.value;
            displayAssets(allAssets);
        });
    }
}

// Setup assets filters
function setupAssetsFilters() {
    const filterButtons = document.querySelectorAll('.filter-btn');
    filterButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active class from all
            filterButtons.forEach(b => b.classList.remove('active'));
            // Add active to clicked
            btn.classList.add('active');
            // Update filter
            currentFilter = btn.getAttribute('data-filter');
            displayAssets(allAssets);
        });
    });
}

// Setup asset modal handlers
function setupAssetModal() {
    // Close button
    document.getElementById('closeAssetPreview')?.addEventListener('click', closeAssetModal);

    // Click outside to close
    document.getElementById('assetPreviewModal')?.addEventListener('click', (e) => {
        if (e.target.id === 'assetPreviewModal') {
            closeAssetModal();
        }
    });

    // Open in main preview button
    document.getElementById('openInMainPreview')?.addEventListener('click', openInMainPreview);

    // Open in explorer button
    document.getElementById('openInExplorer')?.addEventListener('click', () => {
        if (currentAsset) {
            openMediaFolder();
        }
    });

    // ESC key to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const modal = document.getElementById('assetPreviewModal');
            if (modal && modal.style.display === 'flex') {
                closeAssetModal();
            }
        }
    });
}

async function openMediaFolder() {
    try {
        await pywebview.api.open_media_folder();
    } catch (err) {
        toast(`Error: ${err.message}`, 'error');
    }
}

async function playMedia(filePath) {
    try {
        await pywebview.api.play_media(filePath);
    } catch (err) {
        toast(`Error: ${err.message}`, 'error');
    }
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Terminal command execution
// Terminal output polling for persistent cmd.exe session with xterm.js
let terminalPollInterval = null;
let term = null; // xterm.js Terminal instance

async function startTerminalPolling() {
    if (terminalPollInterval) return; // Already polling

    console.log('[TERMINAL] Starting PTY output polling for xterm.js...');

    terminalPollInterval = setInterval(async () => {
        try {
            const res = await pywebview.api.get_terminal_output();
            if (res.status === 'success' && res.output && term) {
                // Write PTY output directly to xterm.js terminal
                term.write(res.output);
                // Auto-scroll to bottom when new content arrives
                term.scrollToBottom();
            }
        } catch (err) {
            console.error('[TERMINAL] Poll error:', err);
        }
    }, 20); // Poll every 20ms for very responsive output
}

async function executeCommand(command) {
    console.log('🔧 executeCommand() called with:', command);
    if (!command.trim()) {
        console.log('Empty command, ignoring');
        return;
    }

    // Handle special UI-only commands
    if (command === 'clear') {
        clearConsole();
        setTerminalStatus(job.running ? 'Busy...' : 'Ready', job.running ? 'warning' : 'info');
        focusInput();
        return;
    }

    if (command === 'help') {
        appendConsole('=== Manim Studio Terminal ===', 'info');
        appendConsole('This is a real cmd.exe session!', 'info');
        appendConsole('', 'info');
        appendConsole('Special commands:', 'info');
        appendConsole('  clear - clear console display', 'info');
        appendConsole('  help - show this help', 'info');
        appendConsole('', 'info');
        appendConsole('All other commands run in persistent cmd.exe:', 'info');
        appendConsole('  pip install <package> - uses venv pip automatically', 'info');
        appendConsole('  claude - use Claude Code AI (if installed)', 'info');
        appendConsole('  dir, cd, echo, etc. - normal cmd.exe commands', 'info');
        setTerminalStatus(job.running ? 'Busy...' : 'Ready', job.running ? 'warning' : 'info');
        focusInput();
        return;
    }

    // Show command like a real terminal
    appendConsole(`> ${command}`, 'command');
    setTerminalStatus('Running...', 'warning');

    try {
        console.log('[TERMINAL] Sending command to persistent cmd.exe...');
        const res = await pywebview.api.execute_command(command);

        // Output is handled by polling (get_terminal_output), just check for errors
        if (res.status === 'error' && res.message) {
            appendConsole(res.message, 'error');
            setTerminalStatus('Error', 'error');
        } else {
            setTerminalStatus('Ready', 'success');

            // Refresh system info after pip commands
            if (command.startsWith('pip ')) {
                setTimeout(() => loadSystemInfo(), 1500);
            }
        }
    } catch (err) {
        appendConsole(`Error: ${err.message}`, 'error');
        setTerminalStatus('Error', 'error');
    } finally {
        focusInput();
    }
}

// System info
async function loadSystemInfo() {
    console.log('📊 loadSystemInfo() called');
    try {
        console.log('Calling pywebview.api.get_system_info()...');
        const info = await pywebview.api.get_system_info();
        console.log('System info received:', info);

        // Set all system info fields
        document.getElementById('pythonVersion').textContent = info.python_version ? info.python_version.split('\n')[0] : 'Unknown';
        document.getElementById('manimVersion').textContent = info.manim_version || 'Not installed';
        document.getElementById('platform').textContent = info.platform || 'Unknown';
        document.getElementById('baseDir').textContent = info.base_dir || '-';
        document.getElementById('mediaDir').textContent = info.media_dir || '-';
        document.getElementById('venvPath').textContent = info.venv_path || 'Not in virtual environment';
        document.getElementById('pythonExe').textContent = info.python_exe || '-';

        // Set status indicators
        const venvStatus = document.getElementById('venvStatus');
        if (info.venv_path) {
            venvStatus.textContent = 'Active';
            venvStatus.className = 'status-badge success';
        } else {
            venvStatus.textContent = 'Not Active';
            venvStatus.className = 'status-badge warning';
        }

        const manimStatus = document.getElementById('manimStatus');
        if (info.manim_installed) {
            manimStatus.textContent = 'Installed';
            manimStatus.className = 'status-badge success';
        } else {
            manimStatus.textContent = 'Not Installed';
            manimStatus.className = 'status-badge error';
        }

        // Check LaTeX status
        checkLatexStatus();

        console.log('✅ System info loaded successfully');
    } catch (err) {
        console.error('❌ System info error:', err);
    }
}

// Check LaTeX availability
async function checkLatexStatus() {
    try {
        console.log('🔍 Checking LaTeX status...');
        const result = await pywebview.api.check_prerequisites();

        const latexStatusElement = document.getElementById('latexStatus');
        const latexCard = document.getElementById('latexStatusCard');
        const latexStatusBtn = document.getElementById('latexStatusBtn');

        if (result.status === 'success' && result.results.latex.installed) {
            // LaTeX found
            const variant = result.results.latex.variant || 'Installed';

            // Update system panel
            latexStatusElement.innerHTML = `
                <span class="status-indicator found"></span>
                <span style="flex: 1;">✓ ${variant}</span>
            `;
            latexCard.className = 'info-card success';

            // Update header button
            latexStatusBtn.className = 'status-btn found';
            latexStatusBtn.title = `LaTeX Status - ${variant}`;
            latexStatusBtn.innerHTML = `
                <span class="status-dot found"></span>
                <span class="status-text">LaTeX ✓</span>
            `;

            console.log('✅ LaTeX found:', variant);
        } else {
            // LaTeX not found

            // Update system panel
            latexStatusElement.innerHTML = `
                <span class="status-indicator missing"></span>
                <span style="flex: 1;">✗ Not Found - <a href="#" onclick="window.open('https://miktex.org/download'); return false;" style="color: var(--accent-warning); text-decoration: underline;">Install MiKTeX</a></span>
            `;
            latexCard.className = 'info-card warning';

            // Update header button
            latexStatusBtn.className = 'status-btn missing';
            latexStatusBtn.title = 'LaTeX Status - Not Found (Click to download MiKTeX)';
            latexStatusBtn.innerHTML = `
                <span class="status-dot missing"></span>
                <span class="status-text">LaTeX ✗</span>
            `;

            console.log('⚠️ LaTeX not found');
        }
    } catch (err) {
        console.error('❌ LaTeX check error:', err);
        const latexStatusElement = document.getElementById('latexStatus');
        const latexStatusBtn = document.getElementById('latexStatusBtn');

        latexStatusElement.innerHTML = `
            <span class="status-indicator missing"></span>
            <span style="flex: 1;">Error checking</span>
        `;

        latexStatusBtn.className = 'status-btn missing';
        latexStatusBtn.title = 'LaTeX Status - Error checking';
        latexStatusBtn.innerHTML = `
            <span class="status-dot missing"></span>
            <span class="status-text">LaTeX ?</span>
        `;
    }
}

// Settings
async function loadSettings() {
    try {
        const settings = await pywebview.api.get_settings();

        document.getElementById('qualitySelect').value = settings.quality || '720p';
        document.getElementById('fpsSelect').value = settings.fps || 30;
        document.getElementById('formatSelect').value = settings.format || 'MP4 Video';

        if (editor && settings.font_size) {
            editor.updateOptions({ fontSize: settings.font_size });
        }
    } catch (err) {
        console.error('Failed to load settings:', err);
    }
}

async function saveSettings() {
    try {
        const settings = {
            quality: document.getElementById('qualitySelect').value,
            fps: parseInt(document.getElementById('fpsSelect').value),
            format: document.getElementById('formatSelect').value,
            font_size: editor ? editor.getOption(monaco.editor.EditorOption.fontSize) : 14
        };

        await pywebview.api.update_settings(settings);
    } catch (err) {
        console.error('Failed to save settings:', err);
    }
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    // Initialize editor (doesn't require PyWebView API)
    initializeEditor();
});

// Detect app closing to prevent API calls during shutdown
window.addEventListener('beforeunload', () => {
    console.log('[SHUTDOWN] App is closing, setting isAppClosing flag');
    isAppClosing = true;
});

// Wait for PyWebView to be ready before using API
window.addEventListener('pywebviewready', () => {
    console.log('============================================');
    console.log('✅ PyWebView ready event fired!');
    console.log('============================================');
    console.log('pywebview object:', typeof pywebview);
    console.log('pywebview.api:', typeof pywebview?.api);

    if (typeof pywebview !== 'undefined' && pywebview.api) {
        console.log('✓ PyWebView API is available');
        console.log('Available API methods:', Object.keys(pywebview.api));
    } else {
        console.error('✗ PyWebView API is NOT available!');
    }

    // Load initial data (requires PyWebView API)
    console.log('============================================');
    console.log('Loading initial data...');
    console.log('============================================');

    console.log('[INIT] 1. Loading settings...');
    loadSettings();

    console.log('[INIT] 2. Loading system info...');
    loadSystemInfo();

    console.log('[INIT] 2.5. Checking LaTeX status for header button...');
    checkLatexStatus();

    console.log('[INIT] 3. Refreshing assets...');
    refreshAssets();

    console.log('[INIT] 4. Starting auto-save...');
    startAutosave();

    console.log('[INIT] 5. Checking for unsaved work (delayed)...');
    // Delay autosave check to ensure app is fully loaded
    setTimeout(() => {
        checkForAutosaves();
    }, 2000);  // Wait 2 seconds for app to fully initialize

    console.log('[INIT] 6. Will initialize terminal when ready...');
    // Terminal initialization happens below (after Terminal constructor is loaded)

    // Auto-refresh system info every 1 minute (60000ms)
    setInterval(() => {
        // Only refresh if system tab is active to avoid unnecessary API calls
        const systemPanel = document.getElementById('system-panel');
        if (systemPanel && systemPanel.classList.contains('active')) {
            console.log('🔄 Auto-refreshing system info...');
            loadSystemInfo();
        }
    }, 60000); // 60 seconds

    // Setup assets functionality
    setupAssetsSearch();
    setupAssetsFilters();
    setupAssetModal();

    // Tab switching functionality
    const tabPills = document.querySelectorAll('.tab-pill');
    const tabPanels = document.querySelectorAll('.tab-panel');

    tabPills.forEach(pill => {
        pill.addEventListener('click', () => {
            const tabName = pill.getAttribute('data-tab');
            console.log(`[TAB] Switching to tab: ${tabName}`);

            // Remove active class from all pills and panels
            tabPills.forEach(p => p.classList.remove('active'));
            tabPanels.forEach(panel => panel.classList.remove('active'));

            // Add active class to clicked pill and corresponding panel
            pill.classList.add('active');
            document.getElementById(`${tabName}-panel`)?.classList.add('active');

            // Refresh assets when assets tab is clicked
            if (tabName === 'assets') {
                console.log('[TAB] Assets tab selected, refreshing assets...');
                refreshAssets();
            }

            console.log(`Switched to ${tabName} tab`);
        });
    });

    // LaTeX status button click handler
    document.getElementById('latexStatusBtn')?.addEventListener('click', async () => {
        const result = await pywebview.api.check_prerequisites();
        if (result.status === 'success' && !result.results.latex.installed) {
            // If LaTeX is not installed, open download page
            window.open('https://miktex.org/download');
        } else {
            // If LaTeX is installed, switch to system tab to show details
            document.querySelectorAll('.tab-pill').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.remove('active'));
            document.querySelector('[data-tab="system"]')?.classList.add('active');
            document.getElementById('system-panel')?.classList.add('active');
        }
    });

    // Button event listeners
    document.getElementById('newFileBtn')?.addEventListener('click', newFile);
    document.getElementById('openFileBtn')?.addEventListener('click', openFile);
    document.getElementById('saveFileBtn')?.addEventListener('click', saveFile);
    document.getElementById('saveAsBtn')?.addEventListener('click', saveFileAs);
    document.getElementById('renderBtn')?.addEventListener('click', renderAnimation);
    document.getElementById('previewBtn')?.addEventListener('click', quickPreview);
    document.getElementById('stopBtn')?.addEventListener('click', stopActiveRender);
    document.getElementById('refreshAssetsBtn')?.addEventListener('click', refreshAssets);
    document.getElementById('clearErrorsBtn')?.addEventListener('click', clearErrors);
    document.getElementById('openAssetsFolderBtn')?.addEventListener('click', openMediaFolder);
    document.getElementById('openMediaFolderBtn')?.addEventListener('click', openMediaFolder);
    document.getElementById('refreshSystemBtn')?.addEventListener('click', loadSystemInfo);
    document.getElementById('settingsBtn')?.addEventListener('click', () => {
        document.getElementById('settingsModal')?.classList.add('show');
    });

    // Modal close functionality
    document.querySelectorAll('.close-btn, [data-modal]').forEach(btn => {
        btn.addEventListener('click', () => {
            const modalId = btn.getAttribute('data-modal');
            if (modalId) {
                document.getElementById(modalId)?.classList.remove('show');
            }
        });
    });

    // Copy console output button - copies all terminal content
    document.getElementById('copyOutputBtn')?.addEventListener('click', () => {
        if (term) {
            try {
                // Get all visible lines from the terminal buffer
                const buffer = term.buffer.active;
                let text = '';

                // Read all lines from the buffer
                for (let i = 0; i < buffer.length; i++) {
                    const line = buffer.getLine(i);
                    if (line) {
                        text += line.translateToString(true) + '\n';
                    }
                }

                // Copy to clipboard
                navigator.clipboard.writeText(text).then(() => {
                    toast('Copied', 'success');
                    console.log('[TERMINAL] Copied', text.split('\n').length, 'lines to clipboard');
                }).catch(err => {
                    toast('Copy failed', 'error');
                    console.error('[TERMINAL] Copy failed:', err);
                });
            } catch (err) {
                console.error('[TERMINAL] Error copying terminal content:', err);
                toast('Copy failed', 'error');
            }
        } else {
            toast('Terminal not ready', 'warning');
        }
    });

    // Clear console button - reset terminal to original state
    document.getElementById('clearOutputBtn')?.addEventListener('click', async () => {
        if (term) {
            // Clear the terminal screen
            term.clear();

            // Send cls command to PTY to reset cmd.exe
            try {
                await pywebview.api.send_terminal_command('cls\r\n');
                toast('Cleared', 'success');
            } catch (err) {
                console.error('[TERMINAL] Error clearing:', err);
                toast('Clear failed', 'error');
            }
        } else {
            toast('Not ready', 'warning');
        }
    });

    // Initialize xterm.js terminal emulator
    function initializeTerminal() {
        console.log('[TERMINAL] Initializing xterm.js terminal...');

        const terminalContainer = document.getElementById('terminalContainer');
        if (!terminalContainer) {
            console.error('❌ Terminal container not found!');
            return;
        }

        // Check if Terminal constructor is available (try both window.Terminal and global Terminal)
        const TerminalConstructor = window.Terminal || (typeof Terminal !== 'undefined' ? Terminal : null);

        if (!TerminalConstructor) {
            console.error('❌ xterm.js Terminal constructor not available!');
            terminalContainer.innerHTML = '<div style="color: #ff6b6b; padding: 20px; font-family: monospace;">Error: xterm.js library not loaded<br>Terminal constructor not found</div>';
            return;
        }

        console.log('✅ Terminal constructor found, creating instance...');

        try {
            // Create terminal instance
            term = new TerminalConstructor({
                cursorBlink: true,
                cursorStyle: 'block',
                fontSize: 14,
                fontFamily: 'Consolas, "Courier New", monospace',
                lineHeight: 1.2,
                letterSpacing: 0,
                windowsMode: true, // Enable Windows-specific PTY handling
                theme: {
                    background: '#0c0c0c',
                    foreground: '#cccccc',
                    cursor: '#ffffff',
                    cursorAccent: '#000000',
                    selection: 'rgba(255, 255, 255, 0.3)',
                    black: '#0c0c0c',
                    red: '#c50f1f',
                    green: '#13a10e',
                    yellow: '#c19c00',
                    blue: '#0037da',
                    magenta: '#881798',
                    cyan: '#3a96dd',
                    white: '#cccccc',
                    brightBlack: '#767676',
                    brightRed: '#e74856',
                    brightGreen: '#16c60c',
                    brightYellow: '#f9f1a5',
                    brightBlue: '#3b78ff',
                    brightMagenta: '#b4009e',
                    brightCyan: '#61d6d6',
                    brightWhite: '#f2f2f2'
                },
                allowTransparency: false,
                scrollback: 10000,
                fastScrollModifier: 'shift',
                fastScrollSensitivity: 5,
                cols: 80,
                rows: 24
            });

            // Open terminal in container
            term.open(terminalContainer);
            console.log('✅ Terminal opened in container');

            // Focus terminal so it can receive input immediately
            term.focus();

            // Calculate terminal size based on container - auto-sizing like HTML
            function calculateTerminalSize() {
                // Get actual container dimensions
                const rect = terminalContainer.getBoundingClientRect();
                const width = rect.width - 20; // Account for padding
                const height = rect.height - 20;

                // Get actual character dimensions from xterm's render service
                let charWidth = 9;
                let charHeight = 17;

                try {
                    const core = term._core;
                    if (core && core._renderService && core._renderService.dimensions) {
                        charWidth = core._renderService.dimensions.css.cell.width || 9;
                        charHeight = core._renderService.dimensions.css.cell.height || 17;
                    }
                } catch (e) {
                    // Use defaults if can't access internal API
                }

                // Calculate columns and rows to fill the space
                const cols = Math.max(10, Math.floor(width / charWidth));
                const rows = Math.max(5, Math.floor(height / charHeight));

                return { cols, rows };
            }

            // Wait for terminal to render, then calculate and apply proper size
            setTimeout(() => {
                const size = calculateTerminalSize();
                console.log(`[TERMINAL] Initial auto-size: ${size.cols}x${size.rows} (container: ${terminalContainer.clientWidth}x${terminalContainer.clientHeight})`);

                if (size.cols > 0 && size.rows > 0) {
                    term.resize(size.cols, size.rows);
                    lastCols = size.cols;
                    lastRows = size.rows;

                    // Notify backend of terminal size (skip if app is closing)
                    if (!isAppClosing) {
                        pywebview.api.resize_terminal(size.cols, size.rows).catch(err => {
                            // Ignore errors if app is closing
                            if (!isAppClosing) {
                                console.error('[TERMINAL] Error resizing PTY:', err);
                            }
                        });
                    }
                }
            }, 200);

            // Force another resize after a bit to ensure proper sizing
            setTimeout(() => {
                const size = calculateTerminalSize();
                if (size.cols > 0 && size.rows > 0 && (size.cols !== lastCols || size.rows !== lastRows)) {
                    console.log(`[TERMINAL] Secondary auto-size adjustment: ${size.cols}x${size.rows}`);
                    term.resize(size.cols, size.rows);
                    if (!isAppClosing) {
                        pywebview.api.resize_terminal(size.cols, size.rows).catch(() => {});
                    }
                    lastCols = size.cols;
                    lastRows = size.rows;
                }
            }, 500);

            // Send user input to PTY backend
            term.onData(async (data) => {
                try {
                    await pywebview.api.send_terminal_command(data);
                } catch (err) {
                    console.error('[TERMINAL] Error sending data:', err);
                }
            });

            // Enable copy/paste support
            term.attachCustomKeyEventHandler((event) => {
                // Ctrl+Shift+C - Copy (when text is selected)
                if (event.ctrlKey && event.shiftKey && event.key === 'C' && term.hasSelection()) {
                    const selection = term.getSelection();
                    navigator.clipboard.writeText(selection).catch(err => {
                        console.error('[TERMINAL] Copy failed:', err);
                    });
                    return false; // Prevent default
                }

                // Ctrl+Shift+V - Paste
                if (event.ctrlKey && event.shiftKey && event.key === 'V' && event.type === 'keydown') {
                    navigator.clipboard.readText().then(text => {
                        if (text) {
                            pywebview.api.send_terminal_command(text);
                        }
                    }).catch(err => {
                        console.error('[TERMINAL] Paste failed:', err);
                    });
                    return false; // Prevent default
                }

                return true; // Allow other keys
            });

            // Selection-based copy (when user selects text and releases mouse)
            term.onSelectionChange(() => {
                if (term.hasSelection()) {
                    const selection = term.getSelection();
                    if (selection) {
                        navigator.clipboard.writeText(selection).catch(err => {
                            console.log('[TERMINAL] Auto-copy failed:', err);
                        });
                    }
                }
            });

            // Right-click context menu for paste
            terminalContainer.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                navigator.clipboard.readText().then(text => {
                    if (text) {
                        pywebview.api.send_terminal_command(text);
                    }
                }).catch(err => {
                    console.error('[TERMINAL] Paste failed:', err);
                });
            });

            // Handle terminal resize - auto-size on container changes
            let lastCols = 10;
            let lastRows = 5;
            let resizeTimeout = null;

            const resizeObserver = new ResizeObserver(() => {
                if (term && terminalContainer) {
                    // Debounce resize to avoid too many updates
                    if (resizeTimeout) {
                        clearTimeout(resizeTimeout);
                    }

                    resizeTimeout = setTimeout(() => {
                        const size = calculateTerminalSize();

                        // Only resize if dimensions actually changed significantly
                        if (size.cols > 0 && size.rows > 0 && (size.cols !== lastCols || size.rows !== lastRows)) {
                            console.log(`[TERMINAL] Auto-resizing from ${lastCols}x${lastRows} to ${size.cols}x${size.rows}`);
                            term.resize(size.cols, size.rows);

                            // Notify backend PTY of new size (skip if app is closing)
                            if (!isAppClosing) {
                                pywebview.api.resize_terminal(size.cols, size.rows).catch(err => {
                                    // Ignore errors if app is closing
                                    if (!isAppClosing) {
                                        console.error('[TERMINAL] Error resizing PTY:', err);
                                    }
                                });
                            }

                            lastCols = size.cols;
                            lastRows = size.rows;
                        }
                    }, 100); // Wait 100ms for resize to settle
                }
            });
            resizeObserver.observe(terminalContainer);

            // Also listen to window resize for better responsiveness
            window.addEventListener('resize', () => {
                if (resizeTimeout) {
                    clearTimeout(resizeTimeout);
                }
                resizeTimeout = setTimeout(() => {
                    const size = calculateTerminalSize();
                    if (size.cols > 0 && size.rows > 0 && term) {
                        term.resize(size.cols, size.rows);
                        if (!isAppClosing) {
                            pywebview.api.resize_terminal(size.cols, size.rows).catch(() => {});
                        }
                        lastCols = size.cols;
                        lastRows = size.rows;
                    }
                }, 100);
            });

            console.log('✅ xterm.js terminal fully initialized and ready');

            // Now start polling for PTY output
            console.log('[TERMINAL] Starting PTY output polling...');
            startTerminalPolling();
        } catch (err) {
            console.error('❌ Error initializing terminal:', err);
            terminalContainer.innerHTML = `<div style="color: #ff6b6b; padding: 20px; font-family: monospace;">Error initializing terminal:<br>${err.message}</div>`;
        }
    }

    // Try to initialize terminal - check multiple times to handle async script loading
    let terminalInitialized = false;

    function tryInitTerminal() {
        if (terminalInitialized) {
            console.log('[TERMINAL] Already initialized, skipping...');
            return;
        }

        const TerminalConstructor = window.Terminal || (typeof Terminal !== 'undefined' ? Terminal : null);

        if (TerminalConstructor) {
            console.log('[TERMINAL] Terminal constructor found, initializing...');
            terminalInitialized = true;
            initializeTerminal();
        } else {
            console.log('[TERMINAL] Terminal constructor not yet available, will retry...');
        }
    }

    // Try immediately
    tryInitTerminal();

    // If not found, retry after script loads
    if (!terminalInitialized) {
        setTimeout(tryInitTerminal, 500);
    }

    // Render Quality select - show/hide custom resolution
    document.getElementById('qualitySelect')?.addEventListener('change', (event) => {
        const customResDiv = document.getElementById('customResolutionDiv');
        if (customResDiv) {
            if (event.target.value === 'custom') {
                customResDiv.style.display = 'block';
            } else {
                customResDiv.style.display = 'none';
            }
        }
        saveSettings();
    });

    // Render FPS select - show/hide custom FPS
    document.getElementById('fpsSelect')?.addEventListener('change', (event) => {
        const customFpsDiv = document.getElementById('customFpsDiv');
        if (customFpsDiv) {
            if (event.target.value === 'custom') {
                customFpsDiv.style.display = 'block';
            } else {
                customFpsDiv.style.display = 'none';
            }
        }
        saveSettings();
    });

    // Preview Quality select - show/hide custom resolution
    document.getElementById('previewQualitySelect')?.addEventListener('change', (event) => {
        const customResDiv = document.getElementById('previewCustomResolutionDiv');
        if (customResDiv) {
            if (event.target.value === 'custom') {
                customResDiv.style.display = 'block';
            } else {
                customResDiv.style.display = 'none';
            }
        }
        saveSettings();
    });

    // Preview FPS select - show/hide custom FPS
    document.getElementById('previewFpsSelect')?.addEventListener('change', (event) => {
        const customFpsDiv = document.getElementById('previewCustomFpsDiv');
        if (customFpsDiv) {
            if (event.target.value === 'custom') {
                customFpsDiv.style.display = 'block';
            } else {
                customFpsDiv.style.display = 'none';
            }
        }
        saveSettings();
    });

    // Save settings on changes
    document.getElementById('formatSelect')?.addEventListener('change', saveSettings);
    document.getElementById('customWidth')?.addEventListener('change', saveSettings);
    document.getElementById('customHeight')?.addEventListener('change', saveSettings);
    document.getElementById('customFps')?.addEventListener('change', saveSettings);
    document.getElementById('previewCustomWidth')?.addEventListener('change', saveSettings);
    document.getElementById('previewCustomHeight')?.addEventListener('change', saveSettings);
    document.getElementById('previewCustomFps')?.addEventListener('change', saveSettings);

    // Font size control
    document.getElementById('fontSizeSelect')?.addEventListener('change', (event) => {
        const fontSize = parseInt(event.target.value, 10) || 14;
        if (editor) {
            editor.updateOptions({ fontSize: fontSize });
            saveSettings();
        }
    });

    // Initial status
    setTerminalStatus('Ready', 'success');
    appendConsole('Manim Studio Desktop - Ready', 'success');
    appendConsole('Type "help" for available commands', 'info');

    console.log('Manim Studio Desktop initialized');
});
