import esbuild from 'rollup-plugin-esbuild';

const plugins = [
    esbuild({
        tsconfig: 'tsconfig.json',
        target: 'esnext',
        minify: true,
    }),
];

export default {
    input: [
        'src/main.ts',
        'src/widget.ts',
    ],
    output: {
        dir: 'jupyter_widget_ws_example/static',
        format: 'esm',
        sourcemap: true,
        plugins: [],
    },
    plugins,
};