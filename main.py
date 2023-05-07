#!/usr/bin/env python3

import os
import torch
from typing import Union
from transformers import AutoModelForCausalLM, AutoTokenizer
from evals.api import CompletionFn, CompletionResult
from evals.registry import Registry
from evals.cli.oaieval import get_parser, run

model_name = 'OpenAssistant/stablelm-7b-sft-v7-epoch-3'
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16).eval().cuda()

def prompt_json_to_str(prompt):
    if isinstance(prompt, str):
        # TODO: Add prefix about being a helpful assistant
        return '<|prompter|>' + prompt + '<|endoftext|><|assistant|>'

    prompt_str = ''
    for item in prompt:
        role = item['role']
        content = item['content']
        if role == 'system' and 'name' not in item:
            # TODO: Maybe don't use prefix, but use system if it exists
            prompt_str += '<|prefix_begin|>' + content + '<|prefix_end|>'
        elif role == 'system' and item['name'] == 'example_assistant':
            prompt_str += '<|assistant|>' + content + '<|endoftext|>'
        elif (role == 'system' and item['name'] == 'example_user') or role == 'user':
            prompt_str += '<|prompter|>' + content + '<|endoftext|>'
        else:
            raise
    prompt_str += '<|assistant|>'
    return prompt_str

class OpenAssistantCompletionResult(CompletionResult):
    def __init__(self, response) -> None:
        self.response = response

    def get_completions(self) -> list[str]:
        return [self.response.strip()]

class OpenAssistantCompletionFn(CompletionFn):
    def __init__(self) -> None:
        pass

    def model_output(self, prompt_str):
        inputs = tokenizer(prompt_str, return_tensors="pt", padding=True).to(0)

        if "token_type_ids" in inputs:
            del inputs["token_type_ids"]

        outputs = model.generate(
            **inputs,
            early_stopping=True,
            max_new_tokens=200,
            do_sample=True,
            top_k=40,
            temperature=1.0,
            pad_token_id=tokenizer.eos_token_id,
        )

        output = tokenizer.decode(outputs[0], truncate_before_pattern=[r"\n\n^#", "^'''", "\n\n\n"])
        reply = output.split('<|assistant|>')[-1].replace('<|endoftext|>', '')
        return reply

    def __call__(
        self,
        prompt: Union[str, list[dict[str, str]]],
        **kwargs,
    ) -> OpenAssistantCompletionResult:
        prompt_str = prompt_json_to_str(prompt)
        output = self.model_output(prompt_str)
        return OpenAssistantCompletionResult(output)

class RegistryWithOpenAssistant(Registry):
    def make_completion_fn(self, name: str) -> CompletionFn:
        assert name == 'oasst_completion_fn'
        return OpenAssistantCompletionFn()

    api_model_ids = []

def run_eval(registry, eval_name):
    parser = get_parser()
    args = parser.parse_args(['oasst_completion_fn', eval_name,
        '--record_path', 'runs/' + eval_name + '.json'])

    import logging
    logging.basicConfig(
        format="[%(asctime)s] [%(filename)s:%(lineno)d] %(message)s",
        level=logging.INFO,
        filename=args.log_to_file if args.log_to_file else None,
    )

    import openai
    logging.getLogger("openai").setLevel(logging.WARN)
    if hasattr(openai.error, "set_display_cause"):
        openai.error.set_display_cause()

    run(args, registry)

def run_eval_set(registry, eval_set_name):
    eval_set = registry.get_eval_set(eval_set_name)
    for eval in registry.get_evals(eval_set.evals):
        run_eval(registry, eval.key)

def main():
    os.environ['EVALS_THREAD_TIMEOUT'] = '999999'
    registry = RegistryWithOpenAssistant()
    run_eval_set(registry, 'test')

if __name__ == '__main__':
    main()
