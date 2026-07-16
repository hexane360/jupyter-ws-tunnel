import esbuild from 'rollup-plugin-esbuild';

const plugins = [
    esbuild({
        tsconfig: 'tsconfig.json',
        target: 'esnext',
        minify: true,
    }),
];

export default {
    input: 'src/index.ts',
    output: {
        dir: 'jupyter_widget_ws_example',
        format: 'esm',
        sourcemap: true,
        plugins: [],
    },
    plugins,
};