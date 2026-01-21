/**
 * Backend communication and compilation handling
 */

// Configuration
const CONFIG = {
  // Change this to your backend URL
//   backendUrl: 'https://your-vps-domain.com',
  backendUrl: 'http://localhost:8000',  // For local development
  
  endpoints: {
    compile: '/compile',
    compileSync: '/compile/sync',
    health: '/health',
    connect: '/connect'
  }
};

/**
 * Compile Facto code using Server-Sent Events (streaming)
 */
async function compileWithStreaming(source, options, callbacks) {
  const { onLog, onBlueprint, onError, onStatus, onQueue, onComplete } = callbacks;
  
  const requestBody = {
    source: source,
    power_poles: options.powerPoles || null,
    blueprint_name: options.blueprintName || null,
    no_optimize: options.noOptimize || false,
    json_output: options.jsonOutput || false,
    log_level: options.logLevel || 'info'
  };
  
  let completeCalled = false;
  const callComplete = () => {
    if (!completeCalled) {
      completeCalled = true;
      onComplete?.();
    }
  };
  
  try {
    const response = await fetch(`${CONFIG.backendUrl}${CONFIG.endpoints.compile}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(requestBody)
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.message || `Server error: ${response.status}`);
    }
    
    // Read the SSE stream
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) {
        break;
      }
      
      buffer += decoder.decode(value, { stream: true });
      
      // Process complete SSE messages
      const lines = buffer.split('\n');
      buffer = lines.pop(); // Keep incomplete line in buffer
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          
          try {
            const event = JSON.parse(data);
            
            switch (event.type) {
              case 'log':
                onLog?.(event.content);
                break;
              case 'blueprint':
                onBlueprint?.(event.content);
                break;
              case 'error':
                onError?.(event.content);
                break;
              case 'status':
                onStatus?.(event.content);
                break;
              case 'queue':
                onQueue?.(event.content);
                break;
              case 'end':
                callComplete();
                break;
            }
          } catch (e) {
            console.error('Failed to parse SSE data:', e);
          }
        }
      }
    }
    
    callComplete();
    
  } catch (error) {
    onError?.(error.message);
    callComplete();
  }
}

/**
 * Compile Facto code synchronously (fallback for browsers without SSE support)
 */
async function compileSync(source, options) {
  const requestBody = {
    source: source,
    power_poles: options.powerPoles || null,
    blueprint_name: options.blueprintName || null,
    no_optimize: options.noOptimize || false,
    json_output: options.jsonOutput || false,
    log_level: options.logLevel || 'info'
  };
  
  const response = await fetch(`${CONFIG.backendUrl}${CONFIG.endpoints.compileSync}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(requestBody)
  });
  
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.message || `Server error: ${response.status}`);
  }
  
  return await response.json();
}

/**
 * Check backend health
 */
async function checkHealth() {
  try {
    const response = await fetch(`${CONFIG.backendUrl}${CONFIG.endpoints.health}`, {
      method: 'GET',
      mode: 'cors'
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Record a session connection with the backend
 */
async function connect() {
  try {
    const response = await fetch(`${CONFIG.backendUrl}${CONFIG.endpoints.connect}`, {
      method: 'POST',
      mode: 'cors'
    });
    return response.ok;
  } catch {
    return false;
  }
}

// Export for use in other modules
window.FactoCompiler = {
  config: CONFIG,
  compileWithStreaming,
  compileSync,
  checkHealth,
  connect
};
