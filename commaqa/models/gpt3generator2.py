import logging
import time
import os
from functools import lru_cache

import openai
import requests
import json
from diskcache import Cache
from commaqa.inference.prompt_reader import fit_prompt_into_given_limit


logger = logging.getLogger(__name__)


cache = Cache(os.path.expanduser("~/.cache/gpt3calls"))
openai.api_key ='sk-LTQbgmqXmKGwp9ZIgcZBkZkdxfXYCyFeBNWSGmZsqUgmKI6A'
url = "https://api.chatanywhere.com.cn/v1/completions"


# @cache.memoize()
def cached_openai_call(  # kwargs doesn't work with caching.
    prompt,
    model,
    temperature,
    max_tokens,
    top_p,
    frequency_penalty,
    presence_penalty,
    stop,
    n,
    best_of,
    logprobs,
    stream
):
    return openai.Completion.create(
        prompt=prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        stop=stop,
        n=n,
        best_of=best_of,
        logprobs=logprobs,
        stream=stream
    )


def openai_call(
    prompt,
    model,
    temperature,
    max_tokens,
    top_p,
    frequency_penalty,
    presence_penalty,
    stop,
    n,
    best_of,
    logprobs,
    stream
):
    function = cached_openai_call if temperature == 0 else openai.Completion.create
    return function(
        prompt=prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        stop=stop,
        n=n,
        best_of=best_of,
        logprobs=logprobs,
        stream=stream
    )


@lru_cache(maxsize=1)
def get_gpt_tokenizer():
    from transformers import GPT2Tokenizer

    return GPT2Tokenizer.from_pretrained("gpt2")


class GPT3Generator:
    def __init__(
        self,
        # engine="text-davinci-002",
        engine="gpt-3.5-turbo-instruct",
        temperature=0.8,
        max_tokens=300,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        stop=["\n"],
        retry_after_n_seconds=None,
        n=2,
        best_of=2,
        logprobs=0,
        remove_method="first",
        stream=False
    ):
        self.engine = engine
        self.logprobs = logprobs
        self.n = n
        self.best_of = best_of
        self.presence_penalty = presence_penalty
        self.frequency_penalty = frequency_penalty
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.stop = stop
        self.temperature = temperature
        self.retry_after_n_seconds = retry_after_n_seconds
        self.remove_method = remove_method
        self.stream = stream

        # if "code-davinci" not in engine:
        #     raise Exception("Not allowed to prevent accidental $$ wastage.")
        #
        # if "code-davinci" not in engine and self.retry_after_n_seconds is not None:
        #     raise Exception(
        #         "Retry is only supported for code-davinci as it's free. "
        #         "Using it for other paid models is risky and so is disabled."
        #     )

        if ("davinci" or "gpt-3.5") in engine:
            self.model_tokens_limit = 8000
        else:
            self.model_tokens_limit = 2000

    def generate_text_sequence(self, prompt):
        """
        :param input_text:
        :return: returns a sequence of tuples (string, score) where lower score is better
        """
        # GPT3 can't handle trailing white-space
        prompt = prompt.rstrip()

        prompt = fit_prompt_into_given_limit(
            original_prompt=prompt,
            model_length_limit=self.model_tokens_limit,
            estimated_generation_length=self.max_tokens,
            demonstration_delimiter="\n\n\n",
            shuffle=False,
            remove_method=self.remove_method,
            tokenizer_model_name="gpt2",  # did this before tiktoken was released.
            last_is_test_example=True,
        )

        arguments = {
            "model": self.engine,
            "prompt": prompt,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            # "n": self.n,
            # "best_of": self.best_of,
            "n": 4,
            "best_of": 4,
            "logprobs": self.logprobs,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "stop": self.stop,
            "stream": self.stream
        }
        if self.best_of is not None:
            # arguments["best_of"] = self.best_of
            arguments["best_of"] = 4

        # print("***" * 20)
        # print("arguments is " + str(arguments))
        # print("***" * 20)

        payload = json.dumps(arguments)
        headers = {
            'Authorization': 'Bearer sk-GQFIDgoyWaLpMKyMrV3NNUOgzZ7X8BWof7NrF4HS8QLDpoq0',
            'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
            'Content-Type': 'application/json'
        }

        success = False
        for index in range(500):
            try:
                # response = openai_call(**arguments)
                response = json.loads(requests.request("POST", url, headers=headers, data=payload).text)
                success = True
                break
            except Exception as exception:

                success = False

                tokenizer = get_gpt_tokenizer()
                prompt_num_tokens = len(tokenizer.tokenize(prompt))
                if prompt_num_tokens + arguments["max_tokens"] > self.model_tokens_limit > prompt_num_tokens:
                    last_used_max_tokens = arguments["max_tokens"]
                    updated_max_tokens = self.model_tokens_limit - prompt_num_tokens
                    arguments["max_tokens"] = updated_max_tokens
                    if last_used_max_tokens == updated_max_tokens:
                        break
                    print(
                        f"WARNING: (Round {index}) Decreasing max_tokens from "
                        f"{last_used_max_tokens} to {updated_max_tokens} and retrying."
                    )
                    continue

                if self.retry_after_n_seconds is None:
                    import traceback

                    print(traceback.format_exc())
                    exit()

                print(f"Encountered exception of class: {exception.__class__}")
                if hasattr(exception, "user_message"):
                    print(exception.user_message)
                print(f"Potentially reached OpenAI rate limit. Will try again in {self.retry_after_n_seconds}s.")
                time.sleep(self.retry_after_n_seconds)
                pass

        if not success:
            raise Exception("Could not complete OpenAI call")

        output_seq_score = []

        print()
        print("***" * 20)
        print("response is" + str(response))
        print("***" * 20)


        for index, choice in enumerate(response["choices"]):
            if "logprobs" in choice and "token_logprobs" in choice["logprobs"]:
                probs = []
                for prob, tok in zip(choice["logprobs"]["token_logprobs"], choice["logprobs"]["tokens"]):
                    if tok not in self.stop and tok != "<|endoftext|>":
                        probs.append(prob)
                    else:
                        probs.append(prob)
                        break

                score = -sum(probs) / len(probs) if len(probs) else 100.0
                output_seq_score.append((choice["text"], score))
            else:
                output_seq_score.append((choice["text"], index))

        return sorted(output_seq_score, key=lambda x: x[1])
