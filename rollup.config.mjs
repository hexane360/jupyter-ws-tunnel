import esbuild from 'rollup-plugin-esbuild';

export default {
    input: 'src/index.ts',
    output: {
        dir: 'dist',
        format: 'esm',
        sourcemap: true,
    },
    plugins: [
        esbuild({
            tsconfig: 'tsconfig.json',
            target: 'esnext',
            minify: true,
        }),
    ],
};
