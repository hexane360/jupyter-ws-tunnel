import esbuild from 'rollup-plugin-esbuild';

const plugins = [
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
