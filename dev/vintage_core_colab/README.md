# Vintage CORE Colab evaluation

[Open the evaluator in Colab](https://colab.research.google.com/github/zachnorton14/think.nano/blob/Vintage-CORE/dev/vintage_core_colab/Vintage_CORE_Eval.ipynb)

The notebook explicitly clones or updates `zachnorton14/think.nano` at the
`Vintage-CORE` branch and asserts that branch before running. Set
`RUN_ALL_MODELS=True` to evaluate all three models sequentially, or set it to
`False` and choose one `MODEL_ID`:

- `think-d12-r30`
- `modern-d24`
- `gpt1900-d34`

Each model runs in an isolated subprocess. The notebook evaluates full original,
filtered, and restyled CORE and writes resumable JSON plus summary CSV files to
`/content/vintage-core-results/<model-id>`. Completed models are charted even if
a later model fails.

While `jbduran/vintage-core` remains a private Hugging Face dataset, add an
`HF_TOKEN` secret to the Colab session. The evaluator pins the dataset to the
`v1.0.0` tag.

GPT-1900 d34 should use an A100-class runtime.
