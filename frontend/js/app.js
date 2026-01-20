/**
 * Main application logic
 */

(function() {
  'use strict';
  
  // DOM Elements
  let editor;
  const elements = {
    compileBtn: document.getElementById('compile-btn'),
    btnText: document.querySelector('.btn-text'),
    btnIcon: document.querySelector('.btn-icon'),
    btnSpinner: document.querySelector('.btn-spinner'),
    loadExampleBtn: document.getElementById('load-example'),
    clearEditorBtn: document.getElementById('clear-editor'),
    blueprintName: document.getElementById('blueprint-name'),
    powerPoles: document.getElementById('power-poles'),
    logLevel: document.getElementById('log-level'),
    noOptimize: document.getElementById('no-optimize'),
    jsonOutput: document.getElementById('json-output'),
    logOutput: document.getElementById('log-output'),
    blueprintStatus: document.getElementById('blueprint-status'),
    blueprintOutput: document.getElementById('blueprint-output'),
    blueprintText: document.getElementById('blueprint-text'),
    copyBlueprint: document.getElementById('copy-blueprint'),
    downloadBlueprint: document.getElementById('download-blueprint'),
    tabBtns: document.querySelectorAll('.tab-btn'),
    toastContainer: document.getElementById('toast-container')
  };
  
  // State
  let isCompiling = false;
  let currentExampleIndex = 0;
  const exampleKeys = Object.keys(window.FactoEditor.examples);
  let serverConnected = false;
  let healthCheckInterval = null;
  
  /**
   * Initialize the application
   */
  function init() {
    // Initialize CodeMirror editor
    editor = window.FactoEditor.init('code-editor');
    
    // Load default example
    editor.setValue(window.FactoEditor.examples.blinker);
    
    // Bind event listeners
    bindEvents();
    
    // Start health checks
    startHealthChecks();
  }
  
  /**
   * Bind all event listeners
   */
  function bindEvents() {
    // Compile button
    elements.compileBtn.addEventListener('click', handleCompile);
    
    // Keyboard shortcut (Ctrl+Enter)
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        handleCompile();
      }
    });
    
    // Load example button
    elements.loadExampleBtn.addEventListener('click', loadNextExample);
    
    // Clear editor button
    elements.clearEditorBtn.addEventListener('click', () => {
      editor.setValue('');
      editor.focus();
    });
    
    // Tab switching
    elements.tabBtns.forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
    
    // Copy blueprint
    elements.copyBlueprint.addEventListener('click', copyBlueprintToClipboard);
    
    // Download blueprint
    elements.downloadBlueprint.addEventListener('click', downloadBlueprint);
  }
  
  /**
   * Update connection status indicator
   */
  function updateConnectionStatus(status) {
    const statusDot = document.querySelector('.status-dot');
    const statusEl = document.getElementById('connection-status');
    
    statusDot.className = 'status-dot';
    
    if (status === 'connected') {
      statusDot.classList.add('connected');
      statusEl.title = 'Server connected';
      serverConnected = true;
    } else if (status === 'connecting') {
      statusDot.classList.add('connecting');
      statusEl.title = 'Connecting to server...';
      serverConnected = false;
    } else {
      statusDot.classList.add('disconnected');
      statusEl.title = 'Server disconnected';
      serverConnected = false;
    }
  }
  
  /**
   * Check if backend is healthy
   */
  async function checkBackendHealth(showNotification = false) {
    updateConnectionStatus('connecting');
    
    const isHealthy = await window.FactoCompiler.checkHealth();
    
    if (isHealthy) {
      updateConnectionStatus('connected');
      if (showNotification) {
        showToast('Connected to server', 'success');
      }
    } else {
      updateConnectionStatus('disconnected');
      if (showNotification) {
        showToast('Backend server is not responding. Check if server is running.', 'error');
      }
    }
    
    return isHealthy;
  }
  
  /**
   * Start periodic health checks
   */
  function startHealthChecks() {
    // Initial check
    checkBackendHealth(false);
    
    // Check every 10 seconds
    healthCheckInterval = setInterval(() => {
      checkBackendHealth(false);
    }, 10000);
  }
  
  /**
   * Stop periodic health checks
   */
  function stopHealthChecks() {
    if (healthCheckInterval) {
      clearInterval(healthCheckInterval);
      healthCheckInterval = null;
    }
  }
  
  /**
   * Handle compile button click
   */
  async function handleCompile() {
    if (isCompiling) return;
    
    // Check server connection
    if (!serverConnected) {
      showToast('Server not connected. Checking connection...', 'error');
      const isHealthy = await checkBackendHealth(true);
      if (!isHealthy) {
        return;
      }
    }
    
    const source = editor.getValue().trim();
    
    if (!source) {
      showToast('Please enter some Facto code to compile', 'error');
      return;
    }
    
    // Get options
    const options = {
      blueprintName: elements.blueprintName.value.trim() || null,
      powerPoles: elements.powerPoles.value || null,
      logLevel: elements.logLevel.value,
      noOptimize: elements.noOptimize.checked,
      jsonOutput: elements.jsonOutput.checked
    };
    
    // Update UI
    setCompiling(true);
    clearLog();
    clearBlueprint();
    switchTab('log');
    
    // Compile with streaming
    try {
      await window.FactoCompiler.compileWithStreaming(source, options, {
        onLog: (message) => appendLog(message, 'info'),
        onBlueprint: (blueprint) => setBlueprint(blueprint),
        onError: (error) => {
          appendLog(error, 'error');
          // Check if server connection lost
          if (error.includes('Failed to fetch') || error.includes('NetworkError')) {
            updateConnectionStatus('disconnected');
            checkBackendHealth(false);
          }
        },
        onStatus: (status) => appendLog(status, 'status'),
        onComplete: () => {
          setCompiling(false);
          
          // Auto-switch to blueprint tab if successful
          if (elements.blueprintText.value) {
            switchTab('blueprint');
            showToast('Compilation successful! Blueprint ready to copy.', 'success');
          }
        }
      });
    } catch (error) {
      // Ensure we always stop the spinner even if there's an unexpected error
      setCompiling(false);
      appendLog(`Unexpected error: ${error.message}`, 'error');
      showToast('Compilation failed. Check the log for details.', 'error');
    }
  }
  
  /**
   * Set compiling state
   */
  function setCompiling(compiling) {
    isCompiling = compiling;
    elements.compileBtn.disabled = compiling;
    elements.btnText.textContent = compiling ? 'Compiling...' : 'Compile';
    elements.btnIcon.hidden = compiling;
    elements.btnSpinner.hidden = !compiling;
  }
  
  /**
   * Clear log output
   */
  function clearLog() {
    elements.logOutput.innerHTML = '';
  }
  
  /**
   * Append message to log
   */
  function appendLog(message, type = 'info') {
    // Remove placeholder if present
    const placeholder = elements.logOutput.querySelector('.log-placeholder');
    if (placeholder) {
      placeholder.remove();
    }
    
    const line = document.createElement('div');
    line.className = `log-line log-${type}`;
    line.textContent = message;
    elements.logOutput.appendChild(line);
    
    // Auto-scroll to bottom
    elements.logOutput.scrollTop = elements.logOutput.scrollHeight;
  }
  
  /**
   * Clear blueprint output
   */
  function clearBlueprint() {
    elements.blueprintText.value = '';
    elements.blueprintStatus.hidden = false;
    elements.blueprintOutput.hidden = true;
  }
  
  /**
   * Set blueprint output
   */
  function setBlueprint(blueprint) {
    elements.blueprintText.value = blueprint;
    elements.blueprintStatus.hidden = true;
    elements.blueprintOutput.hidden = false;
  }
  
  /**
   * Switch output tab
   */
  function switchTab(tabName) {
    // Update tab buttons
    elements.tabBtns.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    
    // Update tab content
    document.querySelectorAll('.output-tab').forEach(tab => {
      tab.classList.toggle('active', tab.id === `${tabName}-tab`);
    });
  }
  
  /**
   * Copy blueprint to clipboard
   */
  async function copyBlueprintToClipboard() {
    const blueprint = elements.blueprintText.value;
    
    if (!blueprint) {
      showToast('No blueprint to copy', 'error');
      return;
    }
    
    try {
      await navigator.clipboard.writeText(blueprint);
      showToast('Blueprint copied to clipboard!', 'success');
    } catch (err) {
      // Fallback for older browsers
      elements.blueprintText.select();
      document.execCommand('copy');
      showToast('Blueprint copied to clipboard!', 'success');
    }
  }
  
  /**
   * Download blueprint as file
   */
  function downloadBlueprint() {
    const blueprint = elements.blueprintText.value;
    
    if (!blueprint) {
      showToast('No blueprint to download', 'error');
      return;
    }
    
    const filename = (elements.blueprintName.value.trim() || 'facto-blueprint')
      .replace(/[^a-z0-9]/gi, '_') + '.txt';
    
    const blob = new Blob([blueprint], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    showToast(`Blueprint saved as ${filename}`, 'success');
  }
  
  /**
   * Load next example program
   */
  function loadNextExample() {
    const key = exampleKeys[currentExampleIndex];
    editor.setValue(window.FactoEditor.examples[key]);
    currentExampleIndex = (currentExampleIndex + 1) % exampleKeys.length;
    
    showToast(`Loaded example: ${key}`, 'success');
  }
  
  /**
   * Show toast notification
   */
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    const icon = type === 'success' 
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><polyline points="20 6 9 17 4 12"></polyline></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
    
    toast.innerHTML = `
      <span class="toast-icon">${icon}</span>
      <span class="toast-message">${message}</span>
    `;
    
    elements.toastContainer.appendChild(toast);
    
    // Remove after 4 seconds
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 200);
    }, 4000);
  }
  
  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  
  // Cleanup on page unload
  window.addEventListener('beforeunload', () => {
    stopHealthChecks();
  });
})();
