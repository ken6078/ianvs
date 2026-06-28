# README

## Simple QA

### Prepare Data

Run the dataset preparation script:

`python examples/llm_simple_qa/scripts/prepare_dataset.py`

The script creates the following structure by default:

```
.
├── test_data
│   └── data.jsonl
└── train_data
    └── data.jsonl
```

`train_data/data.jsonl` is empty.

`test_data/data.jsonl` contains three JSONL rows, one JSON object per line:

```json
{"question":"If Xiao Ming has 5 apples, and he gives 3 to Xiao Hua, how many apples does Xiao Ming have left?\nA. 2\nB. 3\nC. 4\nD. 5","answer":"A"}
{"question":"Which of the following numbers is the smallest prime number?\nA. 0\nB. 1\nC. 2\nD. 4","answer":"C"}
{"question":"A rectangle has a length of 10 centimeters and a width of 5 centimeters, what is its perimeter in centimeters?\nA. 20 centimeters\nB. 30 centimeters\nC. 40 centimeters\nD. 50 centimeters","answer":"B"}
```

### Prepare Environment

Install the example dependencies first:

`pip install -r examples/llm_simple_qa/requirements.txt`

Install Sedna from the bundled wheel:

`pip install resources/third_party/sedna-0.6.0.1-py3-none-any.whl`


### Run Ianvs

Run the following command:

`ianvs -f examples/llm_simple_qa/benchmarkingjob.yaml`

## OpenCompass Evaluation

### Prepare Environment

Install OpenCompass from the bundled wheel:

`pip install resources/third_party/sedna-0.6.0.1-py3-none-any.whl`

### Run Evaluation

`python run_op.py examples/llm_simple_qa/testalgorithms/gen/op_eval.py`
