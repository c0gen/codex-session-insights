import {defineConfig} from 'vite';

// The Intel Mac exporter also supports the WebKit shipped with macOS 12.
export default defineConfig({build:{target:['chrome100','safari15']}});
