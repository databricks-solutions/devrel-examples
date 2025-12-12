"""
Evaluation script for Arxiv Knowledge Assistant.

Usage:
    python -m arxiv_demo.eval --endpoint-name agents_arxiv-papers --judge-endpoint databricks-meta-llama-3-1-70b-instruct
"""

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

# Default to creating a new run if finding one is hard
# We will use the WorkspaceClient for everything
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class EvalResult:
    question: str
    ground_truth: str
    answer: str
    score: int
    reasoning: str


class KnowledgeAssistantEvaluator:
    def __init__(self, ka_endpoint: str, judge_endpoint: str):
        self.ka_endpoint = ka_endpoint
        self.judge_endpoint = judge_endpoint
        # Initialize client with default profile or env vars
        self.client = WorkspaceClient()

    def query_assistant(self, question: str) -> str:
        """Query the Knowledge Assistant endpoint."""
        try:
            response = self.client.serving_endpoints.query(
                name=self.ka_endpoint,
                messages=[
                    ChatMessage(role=ChatMessageRole.USER, content=question)
                ],
            )
            # Handle different response structures
            if hasattr(response, "choices") and response.choices:
                return response.choices[0].message.content
            return str(response)
        except Exception as e:
            print(f"Error querying assistant: {e}")
            return "ERROR"

    def judge_answer(self, question: str, answer: str, ground_truth: str) -> tuple[int, str]:
        """Ask an LLM judge to grade the answer."""
        prompt = f"""
You are an impartial judge evaluating the quality of an answer to a question.
Compare the ACTUAL ANSWER with the GROUND TRUTH.

Question: {question}
Ground Truth: {ground_truth}
Actual Answer: {answer}

Score the answer from 1 to 5:
1: Completely incorrect or irrelevant.
2: Major errors or missing key information.
3: Partially correct but misses some nuance.
4: Mostly correct.
5: Excellent, accurate, and complete.

Format your response exactly as JSON:
{{
    "score": <int>,
    "reasoning": "<string>"
}}
"""
        max_retries = 3
        for _ in range(max_retries):
            try:
                response = self.client.serving_endpoints.query(
                    name=self.judge_endpoint,
                    messages=[
                        ChatMessage(role=ChatMessageRole.USER, content=prompt)
                    ],
                    max_tokens=500
                )
                
                content = ""
                if hasattr(response, "choices") and response.choices:
                    content = response.choices[0].message.content
                else:
                    # Fallback for some response types
                    content = str(response)

                # Strip markdown code blocks if present
                content = content.replace("```json", "").replace("```", "").strip()
                
                result = json.loads(content)
                return result.get("score", 0), result.get("reasoning", "No reasoning provided")
            except Exception as e:
                print(f"Error calling judge (retry): {e}")
        
        return 0, "Evaluation failed after retries"

    def run_eval(self, dataset_path: str) -> list[EvalResult]:
        """Run evaluation on a dataset."""
        if not Path(dataset_path).exists():
            print(f"Dataset not found: {dataset_path}")
            return []

        with open(dataset_path, "r") as f:
            dataset = json.load(f)

        results = []
        print(f"Starting evaluation on {len(dataset)} items...")
        
        for i, item in enumerate(dataset):
            question = item["question"]
            ground_truth = item["ground_truth"]
            
            print(f"[{i+1}/{len(dataset)}] Q: {question[:60]}...")
            
            # 1. Get Answer
            answer = self.query_assistant(question)
            
            # 2. Judge
            score, reasoning = self.judge_answer(question, answer, ground_truth)
            
            print(f"  -> Score: {score}/5")
            
            results.append(EvalResult(
                question=question,
                ground_truth=ground_truth,
                answer=answer,
                score=score,
                reasoning=reasoning
            ))

        return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate Knowledge Assistant")
    parser.add_argument("--endpoint", required=True, help="Name of the KA serving endpoint")
    parser.add_argument("--judge", default="databricks-meta-llama-3-1-70b-instruct", help="Name of the LLM judge endpoint")
    parser.add_argument("--dataset", default="evaluation_dataset.json", help="Path to simple JSON dataset")
    
    args = parser.parse_args()
    
    evaluator = KnowledgeAssistantEvaluator(args.endpoint, args.judge)
    results = evaluator.run_eval(args.dataset)
    
    # Summary
    if results:
        avg_score = sum(r.score for r in results) / len(results)
        print("\n" + "="*40)
        print(f"RESULTS SUMMARY")
        print(f"Average Score: {avg_score:.2f} / 5.0")
        print("="*40)
        
        # Save full results
        output_file = "eval_results.json"
        with open(output_file, "w") as f:
            json.dump([vars(r) for r in results], f, indent=2)
        print(f"Full results saved to {output_file}")
    else:
        print("No results generated.")


if __name__ == "__main__":
    main()
