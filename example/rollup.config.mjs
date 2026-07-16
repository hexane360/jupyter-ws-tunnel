import { nodeResolve } from '@rollup/plugin-node-resolve';
import esbuild from 'rollup-plugin-esbuild';

const plugins = [
    // Resolves the bare "jupyter-widget-ws" import to the workspace package;
    // Rollup core only resolves relative/absolute paths on its own.
    nodeResolve(),
    esbuild({
        tsconfig: 'tsconfig.json',
        target: 'esnext',
        minify: true,
    }),
];

const output = {
    dir: 'jupyter_widget_ws_example/static',
    format: 'esm',
    sourcemap: true,
};

export default [
    { input: 'src/main.ts', output, plugins },
    { input: 'src/widget.ts', output, plugins },
];
