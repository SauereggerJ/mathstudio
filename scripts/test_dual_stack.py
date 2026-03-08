import sys
import os
import time
import argparse
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai import ai
import converter
import services.note


def test_prose_repair():
    print("\n==============================================")
    print("      TEST 1: PROSE REPAIR (Text-to-XML)      ")
    print("==============================================")
    snippet = r"""The function $f(x)$ is continuous on the interval $[a, b]$ and differentiable on $(a, b)$. If \(f(a) = f(b)\), then there exists at least one $c$ in $(a, b)$ such that f'(c) = 0. This is Rolle's Theorem."""

    # We will test both models against the standard repair instructions from converter.py
    prompt = (
        "=== REQUEST ===\n"
        "You are an expert LaTeX mechanic. Repair the following text snippet by properly wrapping all English words/prose in \\text{} and protecting all math with $...$.\n"
        "=== FAILED LATEX ===\n"
        f"{snippet}\n"
    )

    print("\n[GEMINI] ----------------")
    try:
        t0 = time.time()
        blocks = ai.gemini.generate_xml_blocks(prompt, "repaired_latex")
        t1 = time.time()
        print(blocks[0] if blocks else "No blocks returned.")
        print(f"Time: {t1-t0:.2f}s")
    except Exception as e:
        print(f"Error: {e}")

    if ai.deepseek:
        print("\n[DEEPSEEK] --------------")
        try:
            t0 = time.time()
            blocks = ai.deepseek.generate_xml_blocks(prompt, "repaired_latex")
            t1 = time.time()
            print(blocks[0] if blocks else "No blocks returned.")
            print(f"Time: {t1-t0:.2f}s")
        except Exception as e:
            print(f"Error: {e}")


def test_term_extraction():
    print("\n==============================================")
    print("     TEST 2: TERM EXTRACTION (Text-to-XML)    ")
    print("==============================================")
    latex = r"""
    \section{Main Results}
    We begin with a fundamental property of metric spaces.
    
    \begin{theorem}[Baire Category Theorem]
    Let $(X, d)$ be a complete metric space. If $\{U_n\}_{n=1}^{\infty}$ is a sequence of dense open subsets of $X$, then the intersection $\bigcap_{n=1}^{\infty} U_n$ is dense in $X$.
    \end{theorem}
    \begin{proof}
    Let $W$ be an arbitrary non-empty open subset of $X$. We must show that $W \cap \bigcap_{n=1}^{\infty} U_n \neq \emptyset$.
    \end{proof}
    
    \begin{definition}
    A set is called \textbf{nowhere dense} if its closure has an empty interior.
    \end{definition}
    """
    
    print("\n[GEMINI] ----------------")
    ai.routing_policy = "gemini_only" 
    t0 = time.time()
    terms, err = converter.extract_terms_batch(latex, start_page=1, end_page=1)
    t1 = time.time()
    if err:
        print(f"Error: {err}")
    else:
        for t in terms: print(t)
    print(f"Time: {t1-t0:.2f}s")

    if ai.deepseek:
        print("\n[DEEPSEEK] --------------")
        ai.routing_policy = "dual_stack" # Text goes to DeepSeek
        t0 = time.time()
        terms, err = converter.extract_terms_batch(latex, start_page=1, end_page=1)
        t1 = time.time()
        if err:
            print(f"Error: {err}")
        else:
            for t in terms: print(t)
        print(f"Time: {t1-t0:.2f}s")

def test_local_linting():
    print("\n==============================================")
    print("        TEST 3: LOCAL SYNTAX VALIDATION       ")
    print("==============================================")
    note_srv = services.note.NoteService()
    
    test_cases = [
        (r"Let $x \in X$ be chosen.", "Expected passing"),
        (r"\begin{theorem} foo \end{lemma}", "Expected unclosed environment/nesting error"),
        (r"We define $f(x) = \begin{cases} 1 & x > 0 \\ 0 & x \le 0 \end{cases}$", "Expected pass (valid ampersands)"),
        (r"Smith & Wesson studied this $x = 2$", "Expected unescaped ampersand error"),
        (r"Wait $\{ f(x)$ is odd", "Expected missing curly brace error"),
        (r"Odd $math$ signs $", "Expected odd $ parity error")
    ]
    
    for case, desc in test_cases:
        print(f"\nEvaluating: '{case}' ({desc})")
        errors = note_srv.lint_latex(case)
        if errors:
            for e in errors: print(f"  ❌ {e}")
        else:
            print("  ✅ Passed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", choices=["repair", "extraction", "lint", "all"], default="all")
    args = parser.parse_args()

    if args.test in ["repair", "all"]:
        test_prose_repair()
    if args.test in ["extraction", "all"]:
        test_term_extraction()
    if args.test in ["lint", "all"]:
        test_local_linting()
