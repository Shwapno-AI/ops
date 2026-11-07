# Excel compiler

A private website for compiling Excel files. Drag in your files, click **Compile**, and download the result.

It lives in the `compiler/` folder of the Shwapno Ops repository, runs as its own Coolify app, and appears in the Operations dashboard under **Connected dashboards → Compiler**.

- **With a template:** the template is filled in, and its design and formulas stay as they are.
- **Without a template:** Qwen AI decides the layout.
- **Instructions:** optional, in Bangla or English.

Qwen only writes the plan. All the numbers are calculated by code, and the saved file is reopened and checked against the source totals. Anything that doesn't match is shown on the result page.

## Set it up in Coolify

1. In your Coolify project, click **+ New** and choose your GitHub repository option, the same way the Operations dashboard is connected.
2. Select `Shwapno-AI/ops`, branch `main`.
3. Set **Build pack** to **Dockerfile**. Set **Base Directory** to `/compiler` and **Dockerfile Location** to `/Dockerfile`.
4. Set **Ports Exposes** to `3000`.
5. Under **Environment Variables**, add:

   | Name | Value |
   |---|---|
   | `APP_PASSWORD` | A password of your choice, used to sign in |
   | `QWEN_API_KEY` | Your Qwen key from [Alibaba Cloud Model Studio](https://www.alibabacloud.com/help/en/model-studio/get-api-key) |
   | `FRAME_ANCESTORS` | `https://ops.shwapno.app`, so the Operations dashboard can show the app inside its page |

6. Under **Persistent Storage**, add a volume with the destination path `/data`. This keeps your results when the app is redeployed.
7. Set the domain to `https://compiler.shwapno.app` (the address the Operations dashboard opens) and click **Deploy**. The first build takes a few minutes.
8. Open the site, sign in, click **Test Qwen connection**, then **Try with sample files**.

The server should have at least 4 GB of memory for large files. A 450,000-row compile used about 1.7 GB in testing.

## Everyday use

1. Drop your source files into **Source files**.
2. If you have a template, drop it into **Template**.
3. Type an instruction if you want something specific.
4. Click **Compile**. You can close the page once the upload finishes; the result will be under **Recent results**.
5. Read **Please check** on the result page, then click **Download Excel**.

If the result isn't right, change the instruction under **Run again**. You don't need to upload the files again.

## What it handles

| In your file | What it does |
|---|---|
| Titles above the table, or a header partway down | Finds the real header |
| Two-line headers, or a label line under the header | Combines them into one header |
| Total, Grand Total or "Total Guard:" rows, or an unlabelled sum at the bottom | Removes them so nothing is counted twice, and lists them |
| `1,234.50`, `(200)`, `300-`, `১২৩`, `৳500` | Reads them as numbers |
| Codes such as `00123` | Keeps the zeros |
| The same outlets repeated across several files | Tells Qwen, and rejects a plan that would count them twice |
| Fake `.xls` files from SAP (really text or HTML) | Reads them correctly |
| Notes and remarks columns | Keeps them unless you ask to remove them |

**File types:** `.xlsx .xlsm .xlsb .xls .ods .csv .tsv .txt`

## Templates

- Design, merged cells, colours, formulas, conditional formatting, Excel tables and macros (`.xlsm`) are kept.
- A column with a formula is never overwritten. The formula is copied down to every new row.
- New rows copy the format of the first data row.
- If the data needs more rows, the Total row moves down and `SUM` ranges grow, including formulas on other sheets.
- If the template already lists outlets, those rows are filled in by matching the outlet.
- Shapes, slicers and form controls may not survive. The result page warns you if your template has them.

## Where your data goes

- **Your files stay on your Coolify server,** in `/data`. They are not stored on GitHub.
- **Sent to Qwen (Alibaba Cloud):** file, sheet and column names, 3 sample rows per table, text above the header, short lists of repeated values such as regions, and template labels.
- **Not sent to Qwen:** the full data, or any values from hidden sheets.
- To send names and structure only, set `QWEN_SAMPLE_ROWS` to `0`. Qwen's plans may be weaker.
- Results and uploaded files are deleted automatically after 7 days.

## Optional settings

Add these under **Environment Variables**, then redeploy.

| Name | Default | What it does |
|---|---|---|
| `QWEN_MODEL` | `qwen-plus` | The model to use, such as `qwen3.8-max` |
| `QWEN_BASE_URL` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | Change it if your key is for the Beijing region: `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `QWEN_SAMPLE_ROWS` | `3` | Sample rows sent per table; `0` sends none |
| `MAX_UPLOAD_MB` | `2048` | Largest total upload for one compile |
| `RETENTION_DAYS` | `7` | Days before results are deleted |
| `JOB_TIMEOUT_MIN` | `120` | Minutes before a stuck compile is stopped |
| `ALLOW_NO_PASSWORD` | `false` | `true` removes the password. Use it only on a private network. |
| `FRAME_ANCESTORS` | (none) | Sites allowed to show the app inside their page, space-separated `https://` addresses. Unset, no site can. |

## If something goes wrong

| What you see | What to do |
|---|---|
| Bad Gateway when opening the site | Check that **Ports Exposes** is `3000`, then redeploy |
| "This site needs a password" | Add `APP_PASSWORD`, then redeploy |
| "Qwen rejected the API key" | Check the key, and that `QWEN_BASE_URL` matches its region |
| A model error from Qwen | Set `QWEN_MODEL` to a model your account has |
| "The server ran out of memory" | Use fewer files, or give the app more memory in Coolify |
| "Results will be lost on each redeploy" | Add persistent storage at `/data` |

## For developers

```
pip install -r requirements.txt pytest
pytest

DATA_DIR=./data APP_PASSWORD=test gunicorn --bind 127.0.0.1:3000 --threads 16 "webapp.app:create_app()"
```

Run these inside the `compiler/` folder. `excelcompiler/` is the compile engine and also runs on its own: `python -m excelcompiler --input in --output out`. `webapp/` is the website. Every push to `main` that changes `compiler/` runs the tests and builds and tries the Docker image (`.github/workflows/compiler-tests.yml`).
