# Vintage CORE Colab evaluation

[Open the evaluator in Colab](https://colab.research.google.com/github/zachnorton14/think.nano/blob/Vintage-CORE/dev/vintage_core_colab/Vintage_CORE_Eval.ipynb)

The notebook explicitly clones `zachnorton14/think.nano` at the `Vintage-CORE`
branch and asserts that branch before running. In the configuration cell, choose
one of:

- `think-d12-r30`
- `modern-d24`
- `gpt1900-d34`

Run one model per Colab session. The notebook evaluates full original, filtered,
and restyled CORE sequentially and writes resumable JSON plus summary CSV files
to `/content/vintage-core-results`.

While `jbduran/vintage-core` remains a private Hugging Face dataset, add an
`HF_TOKEN` secret to the Colab session. The evaluator pins the dataset to the
`v1.0.0` tag.

GPT-1900 d34 should use an A100-class runtime.
