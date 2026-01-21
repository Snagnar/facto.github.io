/**
 * Facto Compiler Configuration
 * 
 * Set the backend URL based on environment.
 * LOCAL_DEV=true uses localhost, otherwise uses production URL.
 */

// Check if running in local development mode
const LOCAL_DEV = window.location.hostname === 'localhost' || 
                  window.location.hostname === '127.0.0.1';

// Configure backend URL based on LOCAL_DEV
if (!LOCAL_DEV) {
    // Production: facto.spokenrobot.com:3000
    window.FACTO_BACKEND_URL = 'https://facto.spokenrobot.com:3000';
} else {
    // Local development: use localhost:8000
    window.FACTO_BACKEND_URL = 'http://localhost:8000';
}
