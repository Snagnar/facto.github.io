/**
 * CodeMirror setup and Facto syntax highlighting
 */

// Define Facto syntax mode for CodeMirror
CodeMirror.defineSimpleMode('facto', {
  start: [
    // Comments
    { regex: /#.*/, token: 'comment' },
    { regex: /\/\/.*/, token: 'comment' },
    
    // Strings
    { regex: /"(?:[^\\]|\\.)*?(?:"|$)/, token: 'string' },
    
    // Numbers (hex, binary, octal, decimal)
    { regex: /0x[0-9a-fA-F]+/, token: 'number' },
    { regex: /0b[01]+/, token: 'number' },
    { regex: /0o[0-7]+/, token: 'number' },
    { regex: /-?\d+/, token: 'number' },
    
    // Keywords
    { 
      regex: /\b(func|return|if|else|for|in|step|import|as)\b/, 
      token: 'keyword' 
    },
    
    // Types
    { 
      regex: /\b(Signal|Memory|Entity|Bundle|int)\b/, 
      token: 'type' 
    },
    
    // Built-in functions
    { 
      regex: /\b(place|any|all|read|write)\b/, 
      token: 'builtin' 
    },
    
    // Operators (word-style)
    { 
      regex: /\b(AND|OR|XOR|and|or)\b/, 
      token: 'operator' 
    },
    
    // Boolean-like
    { 
      regex: /\b(true|false)\b/, 
      token: 'atom' 
    },
    
    // Property access
    { regex: /\.(\w+)/, token: 'property' },
    
    // Identifiers
    { regex: /[a-zA-Z_]\w*/, token: 'variable' },
    
    // Operators
    { regex: /[+\-*\/%<>=!&|^~:]+/, token: 'operator' },
    
    // Brackets
    { regex: /[{}\[\]()]/, token: 'bracket' },
    
    // Punctuation
    { regex: /[;,]/, token: 'punctuation' },
  ],
  meta: {
    lineComment: '#'
  }
});

/**
 * Initialize CodeMirror editor
 */
function initEditor(elementId) {
  const textarea = document.getElementById(elementId);
  
  const editor = CodeMirror.fromTextArea(textarea, {
    mode: 'facto',
    theme: 'facto',
    lineNumbers: true,
    lineWrapping: false,
    indentUnit: 4,
    tabSize: 4,
    indentWithTabs: false,
    matchBrackets: true,
    autoCloseBrackets: true,
    styleActiveLine: true,
    extraKeys: {
      'Ctrl-/': 'toggleComment',
      'Cmd-/': 'toggleComment',
      'Tab': function(cm) {
        if (cm.somethingSelected()) {
          cm.indentSelection('add');
        } else {
          cm.replaceSelection('    ', 'end');
        }
      }
    }
  });
  
  // Apply custom theme class
  editor.getWrapperElement().classList.add('cm-s-facto');
  
  return editor;
}

// Example programs - curated from Factompiler examples
const EXAMPLE_PROGRAMS = {
  blinker: `# Blinking Lamp - A simple counter-controlled lamp
# Demonstrates: Memory, basic arithmetic, entity control

Memory counter: "signal-A";
Signal step_size = 1;

counter.write((counter.read() + step_size) % 60);

Signal blink = counter.read() < 30;

Entity lamp = place("small-lamp", 0, 0);
lamp.enable = blink;`,

  binaryClock: `# 8-Bit Binary Clock
# Demonstrates: Memory, loops conceptually, bit manipulation

Memory counter;

counter.write((counter.read() + 1) % 256);

lamp0 = place("small-lamp", 0, 0);
lamp1 = place("small-lamp", 1, 0);
lamp2 = place("small-lamp", 2, 0);
lamp3 = place("small-lamp", 3, 0);
lamp4 = place("small-lamp", 4, 0);
lamp5 = place("small-lamp", 5, 0);
lamp6 = place("small-lamp", 6, 0);
lamp7 = place("small-lamp", 7, 0);

lamp0.enable = (counter.read() % 2) >= 1;
lamp1.enable = (counter.read() % 4) >= 2;
lamp2.enable = (counter.read() % 8) >= 4;
lamp3.enable = (counter.read() % 16) >= 8;
lamp4.enable = (counter.read() % 32) >= 16;
lamp5.enable = (counter.read() % 64) >= 32;
lamp6.enable = (counter.read() % 128) >= 64;
lamp7.enable = (counter.read() % 256) >= 128;`,

  forLoop: `# For Loop - Create lamps in a row
# Demonstrates: for loops, entity placement

Signal sig = ("signal-A", 1);

for i in 0..5 {
    Entity lamp = place("small-lamp", i, 0);
    lamp.enable = sig > 0;
}`,

  basicArithmetic: `# Basic Arithmetic Operations
# Demonstrates: Signal types, arithmetic, type projection

Signal a = 100;               # implicit type
Signal b = 200;               
Signal c = ("iron-plate", 50); # explicit type

Signal sum = a + b;
Signal diff = c - 10;
Signal quotient = c / 3;
Signal remainder = b % 5;

# Output with explicit type projection
Signal output_val = sum | "signal-output";
Signal output_new_type = (a + b + c) | "copper-plate";`,

  rgbColorCycle: `# HSV Color Cycling Lamp
# Demonstrates: Functions, math, RGB lamps

Memory hue: "signal-H";
hue.write((hue.read() + 1) % 1530);

Signal h = hue.read();
Signal sector = h / 255;
Signal pos = h % 255;

# HSV to RGB conversion
Signal r = ((sector == 0 || sector == 5) : 255)
         + ((sector == 1) : (255 - pos))
         + ((sector == 4) : pos);
Signal g = ((sector == 0) : pos)
         + ((sector == 1 || sector == 2) : 255)
         + ((sector == 3) : (255 - pos));
Signal b = ((sector == 2) : pos)
         + ((sector == 3 || sector == 4) : 255)
         + ((sector == 5) : (255 - pos));

for y in 0..3 {
    for x in 0..3 {
        Entity lamp = place("small-lamp", x, y, 
            {use_colors: 1, always_on: 1, color_mode: 1});
        lamp.r = r | "signal-red";
        lamp.g = g | "signal-green";
        lamp.b = b | "signal-blue";
    }
}`,

  steamBackup: `# Backup Steam Power Controller
# Turns on backup steam when accumulators drop below 20%
# Stays on until they reach 80% (hysteresis prevents flickering)

Signal battery = ("signal-A", 0);  # Wire from accumulator

Memory steam_on: "signal-S";
steam_on.write(1, set=battery < 20, reset=battery >= 80);

Entity steam_switch = place("power-switch", 0, 0);
steam_switch.enable = steam_on.read() > 0;`,

  balancedLoader: `# Balanced Train Loader (MadZuri Pattern)
# Each inserter only activates when its chest is below average

Entity c1 = place("steel-chest", 0, 0);
Entity c2 = place("steel-chest", 1, 0);
Entity c3 = place("steel-chest", 2, 0);

Bundle total = {c1.output, c2.output, c3.output};
Bundle neg_avg = total / -3;

Entity i1 = place("fast-inserter", 0, 1);
Bundle in1 = {neg_avg, c1.output};
i1.enable = any(in1) < 0;

Entity i2 = place("fast-inserter", 1, 1);
Bundle in2 = {neg_avg, c2.output};
i2.enable = any(in2) < 0;

Entity i3 = place("fast-inserter", 2, 1);
Bundle in3 = {neg_avg, c3.output};
i3.enable = any(in3) < 0;`
};

// Export for use in other modules
window.FactoEditor = {
  init: initEditor,
  examples: EXAMPLE_PROGRAMS
};
