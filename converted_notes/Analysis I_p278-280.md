---
title: Note from Analysis I (pp. 278-280)
author: H. Amann
date: 2026-02-17 19:58
tags: [auto-note, Analysis I]
---



## Page 278

### III.4 Connectivity 265

The Generalized Intermediate Value Theorem

Connected sets have the property that their images under continuous functions are also connected. This important fact can be proved easily using the results of Section 2.

**4.5 Theorem** Let $X$ and $Y$ be metric spaces and $f : X \to Y$ continuous. If $X$ is connected, then so is $f(X)$. That is, continuous images of connected sets are connected.

**Proof** Suppose, to the contrary, that $f(X)$ is not connected. Then there are nonempty subsets $V_1$ and $V_2$ of $f(X)$ such that $V_1$ and $V_2$ are open in $f(X)$, $V_1 \cap V_2 = \emptyset$ and $V_1 \cup V_2 = f(X)$. By Proposition 2.26, there are open sets $O_j$ in $Y$ such that $V_j = O_j \cap f(X)$ for $j=1, 2$. Set $U_j := f^{-1}(O_j)$. Then, by Theorem 2.20, $U_j$ is open in $X$ for $j=1, 2$. Moreover
$$U_1 \cup U_2 = X, \quad U_1 \cap U_2 = \emptyset \quad \text{and} \quad U_j \neq \emptyset, j=1, 2 ,$$
which is not possible for the connected set $X$. $\blacksquare$

**4.6 Corollary** Continuous images of intervals are connected.

We will demonstrate in the next two sections that Theorems 4.4 and 4.5 are extremely useful tools for the investigation of real functions. Already we note the following easy consequence of these theorems.

**4.7 Theorem (generalized intermediate value theorem)** Let $X$ be a connected metric space and $f : X \to \mathbb{R}$ continuous. Then $f(X)$ is an interval. In particular, $f$ takes on every value between any two given function values.

**Proof** This follows directly from Theorems 4.4 and 4.5. $\blacksquare$

### Path Connectivity

Let $\alpha, \beta\in \mathbb{R}$ with $\alpha<\beta$. A continuous function $w :[ \alpha, \beta] \to X$ is called a continuous path connecting the end points $w(\alpha)$ and $w(\beta)$.

/AB /AC
/DB
/DB /B4/AC /B5

/DB /B4 /AB/B5

## Page 279

{
  "markdown": "## III Continuous Functions\n\nA metric space $X$ is called **path connected** if, for each pair $(x, y) \\in X \\times X$, there is a continuous path in $X$ connecting $x$ and $y$.\n\nA subset of a metric space is called **path connected** if it is a path connected metric space with respect to the induced metric.\n\n**4.8 Proposition** Any path connected space is connected.\n\n*Proof* Suppose, to the contrary, that there is a metric space $X$ which is path connected, but not connected. Then there are nonempty open sets $O_1, O_2$ in $X$ such that $O_1 \\cap O_2 = \\emptyset$ and $O_1 \\cup O_2 = X$. Choose $x \\in O_1$ and $y \\in O_2$. By hypothesis, there is a path $w :[ \\alpha, \\beta] \\to X$ such that $w(\\alpha)= x$ and $w(\\beta)= y$. Set $U_j := w^{-1} (O_j)$. Then, by Theorem 2.20, $U_j$ is open in $[\\alpha, \\beta]$. We now have $\\alpha$ in $U_1$ and $\\beta$ in $U_2$, as well as $U_1 \\cap U_2 = \\emptyset$ and $U_1 \\cup U_2 = [\\alpha, \\beta]$, and so the interval $[\	\\alpha, \\beta]$ is not connected. This contradicts Theorem 4.4. $\\blacksquare$\n\nLet $E$ be a normed vector space and $a, b \\in E$. The linear structure of $E$ allows us to consider ‘straight’ paths in $E$:\n\\[\nv :[ 0,1] \\to E, \\quad t \\mapsto (1 - t)a + tb . \\quad (4.1)\n\\]\nWe denote the image of the path $v$ by $\\sout{[[a, b]]}$.\n\nA subset $X$ of $E$ is called **convex** if, for each pair $(a, b) \\in X \\times X$, $\\sout{[[a, b]]}$ is contained in $X$.\n\n[Image Placeholder: Convex vs Not convex]\n\n**4.9 Remarks** Let $E$ be a normed vector space.\n\n(a) Every convex subset of $E$ is path connected and connected.\n\n*Proof* Let $X$ be convex and $a, b \\in X$. Then (4.1) defines a path in $X$ connecting $a$ and $b$. Thus $X$ is path connected. Proposition 4.7 then implies that $X$ is connected. $\\blacksquare$\n\n(b) For all $a \\in E$ and $r> 0$, the balls $B_E(a, r)$ and $\\overline{B_E(a, r)}$ are convex.",
  "latex": "\\documentclass{article}\n\\usepackage{amsmath, amssymb, amsthm}\n\\begin{document}\n\n\\setcounter{section}{2}\n\\setcounter{page}{265}\n\\setcounter{chapter}{2}\n\\renewcommand{\\thesection}{III}\n\n\\section*{III Continuous Functions}\n\nA metric space $X$ is called\npath connected if, for each pair\n$(x, y) \\in X \\times X$, there is a continu-\nous path in $X$ connecting $x$ and $y$.\nA subset of a metric space is called\npath connected if it is a path con-\nnected metric space with respect to\nthe induced metric.\n\n\\begin{proposition} Any path connected space is connected.\n\\end{proposition}\n\\begin{proof}\nSuppose, to the contrary, that there is a metric space $X$ which is path\nconnected, but not connected. Then there are nonempty open sets $O_1, O_2$ in $X$\nsuch that $O_1 \\cap O_2 = \\emptyset$ and $O_1 \\cup O_2 = X$. Choose $x \\in O_1$ and $y \\in O_2$. By hypoth-\nesis, there is a path $w :[ \\alpha, \\beta] \\to X$ such that $w(\\alpha)= x$ and $w(\\beta)= y$. Set\n$U_j := w^{-1} (O_j)$. Then, by Theorem 2.20, $U_j$ is open in $[\\alpha, \\beta]$. We now have $\\alpha$\nin $U_1$ and $\\beta$ in $U_2$, as well as $U_1 \\cap U_2 = \\emptyset$ and $U_1 \\cup U_2 = [\\alpha, \\beta]$, and so the interval $[\\alpha, \\beta]$\nis not connected. This contradicts Theorem 4.4. \\qed\n\\end{proof}\n\nLet $E$ be a normed vector space and $a, b \\in E$. The linear structure of $E$ allows\nus to consider `straight' paths in $E$:\n$$v :[ 0,1] \\to E, \\quad t \\mapsto (1 - t)a + tb . \\quad (4.1)$$\nWe denote the image of the path $v$ by $\\sout{[[a, b]]}$.\nA subset $X$ of $E$ is called convex if, for each pair $(a, b) \\in X \\times X$, $\\sout{[[a, b]]}$ is\ncontained in $X$.\n\n\\begin{center}\nConvex Not convex\n\\end{center}\n\n\\begin{remark} Let $E$ be a normed vector space.\n\n(a) Every convex subset of $E$ is path connected and connected.\n\\begin{proof}\nLet $X$ be convex and $a, b \\in X$. Then (4.1) defines a path in $X$ connecting $a$ and $b$.\nThus $X$ is path connected. Proposition 4.7 then implies that $X$ is connected.\n\\end{proof}\n\n(b) For all $a \\in E$ and $r> 0$, the balls $B_E(a, r)$ and $\\overline{B_E(a, r)}$ are convex.\n\\end{remark}\n\n\\end{document}"
}

## Page 280

### III.4 Connectivity 267

**Proof** For $x, y \in \mathrm{BE}(a, r)$ and $t \in [0, 1]$ we have
$$\left\|(1 - t)x + ty - a\right\| = \left\|(1 - t)(x - a) + t(y - a)\right\|$$
$$\leq (1 - t) \|x - a\| + t \|y - a\| < (1 - t)r + tr = r.$$
This inequality implies that $[[x, y]]$ is in $\mathrm{BE}(a, r)$. The second claim can be proved similarly. $\blacksquare$

(c) A subset of $\mathbb{R}$ is convex if and only if it is an interval.

**Proof** Let $X \subseteq \mathbb{R}$ be convex. Then, by (a), $X$ is connected and so, by Theorem 4.4, $X$ is an interval. The claim that intervals are convex is clear. $\blacksquare$

In $\mathbb{R}^2$ there are simple examples of connected sets which are not convex. Even so, in such cases, it seems plausible that any pair of points in the set can be joined with a path which consists of finitely many straight line segments. The following theorem shows that this holds, not just in $\mathbb{R}^2$, but in any normed vector space, so long as the set is open.

/DB /B4/AB
/CY
/B5
/DB /B4/AC /B5
/DB /B4/AB /B5

Let $X$ be a subset of a normed vector space. A function $w :[ \alpha, \beta] \to X$ is called a **polygonal path**$^2$ in $X$ if there are $n \in \mathbb{N}$ and real numbers $\alpha_0,\dots,\alpha_{n+1}$ such that $\alpha = \alpha_0 <\alpha_1 < \cdots <\alpha_{n+1} = \beta$ and
$$w\left(\frac{(1 - t)\alpha_j + t\alpha_{j+1}}{1}\right) = (1 - t)w(\alpha_j) + t w(\alpha_{j+1})$$
for all $t \in [0,1]$ and $j = 0,\dots,n$.

**4.10 Theorem** Let $X$ be a nonempty, open and connected subset of a normed vector space. Then any pair of points of $X$ can be connected by a polygonal path in $X$.

**Proof** Let $a \in X$ and
$$M := \left\{x \in X ; \text{there is a polygonal path in } X \text{ connecting } x \text{ and } a\right\}.$$ 
We now apply the proof technique described in Remark 4.3.

(i) Because $a \in M$, the set $M$ is not empty.

(ii) We next prove that $M$ is open in $X$. Let $x \in M$. Since $X$ is open, there is some $r> 0$ such that $B(x, r) \subseteq X$. By Remark 4.9(b), for each $y \in B(x, r)$, the set $[[x, y]]$ is contained in $B(x, r)$ and so also in $X$. Since $x \in M$, there is a polygonal path $w :[ \alpha, \beta] \to X$ such that $w(\alpha)= a$ and $w(\beta)= x$.

$^2$The function $w :[ \alpha, \beta] \to X$ is clearly left and right continuous at each point, and so, by Proposition 1.12, is continuous. Thus a polygonal path is, in particular, a path.