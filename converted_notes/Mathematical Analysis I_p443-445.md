---
title: Note from Mathematical Analysis I (pp. 443-445)
author: V. A. Zorich
date: 2026-02-17 19:58
tags: [auto-note, Mathematical Analysis I]
---



## Page 443

continuous as a function on $\mathbb{R}$, then the new function $(x,y) \mapsto f(\vec{x})$ will be continuous as a function on $\mathbb{R}^2$. This can be verified either directly from the definition of continuity or by remarking that the function $F$ is the composition $(f \circ \pi_1)(x,y)$ of continuous functions.

In particular, it follows from this, when we take account of c) and e), that the functions
$$f(x,y) = \sin x + e^{xy}, \quad f(x,y) = \arctan\left( \ln\left( |x|+|y|+1 \right) \right)$$
for example, are continuous on $\mathbb{R}^2$.

We remark that the reasoning just used is essentially local, and the fact that the functions $f$ and $F$ studied in Example 7 were defined on the entire real line $\mathbb{R}$ or the plane $\mathbb{R}^2$ respectively was purely an accidental circumstance.

**Example 8** The function $f(x,y)$ of Example 2 is continuous at any point of the space $\mathbb{R}^2$ except $(0, 0)$. We remark that, despite the discontinuity of $f(x,y)$ at this point, the function is continuous in either of its two variables for each fixed value of the other variable.

**Example 9** If a function $f : E \to \mathbb{R}^n$ is continuous on the set $E$ and $\tilde{E}$ is a subset of $E$, then the restriction $f|_{\tilde{E}}$ of $f$ to this subset is continuous on $\tilde{E}$, as follows immediately from the definition of continuity of a function at a point.

We now turn to the global properties of continuous functions. To state them for functions $f : E \to \mathbb{R}^n$, we first give two definitions.

**Definition 8** A mapping $f : E \to \mathbb{R}^n$ of a set $E \subset \mathbb{R}^m$ into $\mathbb{R}^n$ is **uniformly continuous** on $E$ if for every $\varepsilon> 0$ there is a number $\delta> 0$ such that $d(f(x_1),f(x_2)) < \varepsilon$ for any points $x_1,x_2 \in E$ such that $d(x_1, x_2)<\delta$.

As before, the distances $d(x_1,x_2)$ and $d(f(x_1),f(x_2))$ are assumed to be measured in $\mathbb{R}^m$ and $\mathbb{R}^n$ respectively.

When $m = n = 1$, this definition is the definition of uniform continuity of numerical-valued functions that we already know.

**Definition 9** A set $E \subset \mathbb{R}^m$ is **pathwise connected** if for any pair of its points $x_0, x_1$, there exists a path $\Gamma : I \to E$ with support in $E$ and endpoints at these points. In other words, it is possible to go from any point $x_0 \in E$ to any other point $x_1 \in E$ without leaving $E$.

Since we shall not be considering any other concept of connectedness for a set except pathwise connectedness for the time being, for the sake of brevity we shall temporarily call pathwise connected sets simply **connected**.

**Definition 10** A **domain** in $\mathbb{R}^m$ is an open connected set.

## Page 444

7 Functions of Several Variables: Their Limits and Continuity

**Example 10** An open ball $B(\mathbf{a};r)$, $r> 0$, in $\mathbb{R}^m$ is a domain. We already know that $B(\mathbf{a};r)$ is open in $\mathbb{R}^m$. Let us verify that the ball is connected. Let $\mathbf{x}_0 = (x_1^0, \dots, x_m^0)$ and $\mathbf{x}_1 = (x_1^1,\dots, x_m^1)$ be two points of the ball. The path defined by the functions $x_i(t) = t x_i^1 + (1 - t) x_i^0$ ($i = 1,\dots,m$), defined on the closed interval $0 \le t \le 1$, has $\mathbf{x}_0$ and $\mathbf{x}_1$ as its endpoints. In addition, its support lies in the ball $B(\mathbf{a};r)$, since, by Minkowski’s inequality, for any $t \in [0, 1]$,
$$\begin{aligned}
d(\mathbf{x}(t),\mathbf{a}) &= \sqrt{\sum_{i=1}^{m} (x_i(t) - a_i )^2} \\ &= \sqrt{\sum_{i=1}^{m} \left( t(x_i^1 - a_i) + (1 - t)(x_i^0 - a_i) \right)^2} \\ &\le \sqrt{\sum_{i=1}^{m} (t(x_i^1 - a_i ))^2} + \sqrt{\sum_{i=1}^{m} ((1 - t)(x_i^0 - a_i ))^2} \\ &= t \cdot \sqrt{\sum_{i=1}^{m} (x_i^1 - a_i )^2} + (1 - t) \cdot \sqrt{\sum_{i=1}^{m} (x_i^0 - a_i )^2} \\ &< t r + (1 - t) r = r.
\end{aligned}$$

**Example 11** The circle (one-dimensional sphere) of radius $r> 0$ is the subset of $\mathbb{R}^2$ given by the equation $(x_1)^2 + (x_2)^2 = r^2$. Setting $x_1 = r \cos t$, $x_2 = r \sin t$, we see that any two points of the circle can be joined by a path that goes along the circle. Hence a circle is a connected set. However, this set is not a domain in $\mathbb{R}^2$, since it is not open in $\mathbb{R}^2$.

We now state the basic facts about continuous functions in the large.

**Global Properties of Continuous Functions**

a) If a mapping $f : K \to \mathbb{R}^n$ is continuous on a compact set $K \subset \mathbb{R}^m$, then it is uniformly continuous on $K$.
b) If a mapping $f : K \to \mathbb{R}^n$ is continuous on a compact set $K \subset \mathbb{R}^m$, then it is bounded on $K$.
c) If a function $f : K \to \mathbb{R}$ is continuous on a compact set $K \subset \mathbb{R}^m$, then it assumes its maximal and minimal values at some points of $K$.
d) If a function $f : E \to \mathbb{R}$ is continuous on a connected set $E$ and assumes the values $f(\mathbf{a}) = A$ and $f(\mathbf{b})= B$ at points $\mathbf{a},\mathbf{b} \in E$, then for any $C$ between $A$ and $B$, there is a point $\mathbf{c} \in E$ at which $f(\mathbf{c})= C$.

Earlier (Sect. 4.2), when we were studying the local and global properties of functions of one variable, we gave proofs of these properties that extend to the more general case considered here. The only change that must be made in the earlier proofs is that expressions of the type $|x_1 - x_2|$ or $|f(\mathbf{x}_1) - f(\mathbf{x}_2)|$ must be replaced by $d(\mathbf{x}_1, \mathbf{x}_2)$ and $d(f(\mathbf{x}_1),f (\mathbf{x}_2))$, where $d$ is the metric in the space where the points in question are located. This remark applies fully to everything except the last statement d), whose proof we now give.

## Page 445

{
  "markdown": "7.2 Limits and Continuity of Functions of Several Variables 425\n\nProof d) Let $\\Gamma : I \\rightarrow E$ be a path that is a continuous mapping of an interval $[\uprho,\\beta]= I \\subset \\mathbb{R}$ such that $\\Gamma(\\uprho)= a, \\Gamma(\\beta)= b$. By the connectedness of $E$ there exists such a path. The function $f \\circ \\Gamma : I \\rightarrow \\mathbb{R}$, being the composition of continuous functions, is continuous; therefore there is a point $\\gamma \\in[ \\uprho,\\beta]$ on the closed interval $[\uprho,\\beta]$ at which $f \\circ \\Gamma(\\gamma)= C$. Set $c = \\Gamma(\\gamma)$. Then $c \\in E$ and $f(c)= C$.$\\Box$\n\n**Example 12** The sphere $S(0;r)$ deﬁned in $\\mathbb{R}^m$ by the equation\n$$ (x_1)^2 +\\cdots+ (x_m)^2 = r^2, $$\nis a compact set.\n\nIndeed, it follows from the continuity of the function\n$$(x_1,\\ldots,x_m) \\mapsto (x_1)^2 +\\cdots+ (x_m)^2$$\nthat the sphere is closed, and from the fact that $|x_i |\\leq r$ ($i = 1,\\ldots,m $) on the sphere that it is bounded.\n\nThe function\n$$(x_1,\\ldots,x_m) \\mapsto (x_1)^2 +\\cdots+ (x_k )^2 - (x_{k+1})^2 -\\cdots- (x_m)^2$$\nis continuous on all of $\\mathbb{R}^m$, so that its restriction to the sphere is also continuous, and by the global property c) of continuous functions assumes its minimal and max-imal values on the sphere. At the points $(1, 0,\\ldots,0)$ and $(0,\\ldots, 0, 1)$ this function assumes the values $1$ and $-1$ respectively. By the connectedness of the sphere (see Problem 3 at the end of this section), global property d) of continuous functions now enables us to assert that there is a point on the sphere where this function assumes the value $0$.\n\n**Example 13** The open set $\\mathbb{R}^m\\setminus S(0;r)$ for $r> 0$ is not a domain, since it is not connected.\n\nIndeed, if $\\Gamma : I \\rightarrow \\mathbb{R}^m$ is a path one end of which is at the point $x_0 = (0,\\ldots,0)$ and the other at some point $x_1 = (x_1^1,\\ldots,x_m^1 )$ such that $(x_1^1)^2 +\\cdots+ (x_m^1 )^2 >r^2$, then the composition of the continuous functions $\\Gamma : I \\rightarrow \\mathbb{R}^m$ and $f : \\mathbb{R}^m \\rightarrow \\mathbb{R}$, where\n$$(x_1,\\ldots,x_m) \\ f \\mapsto (x_1)^2 +\\cdots+ (x_m)^2,$$nis a continuous function on $I$ assuming values less than $r^2$ at one endpoint and greater than $r^2$ at the other. Hence there is a point $\\gamma$ on $I$ at which $(f \\circ \\Gamma )(\\gamma )= r^2$.\nThen the point $x_{\\gamma} = \\Gamma(\\gamma)$ in the support of the path turns out to lie on the sphere $S(0;r)$. We have thus shown that it is impossible to get out of the ball $B(0;r) \\subset \\mathbb{R}^m$ without intersecting its boundary sphere $S(0;r)$.",
  "latex": "\\documentclass{article}\n\\usepackage{amsmath}\n\\usepackage{amssymb}\n\\begin{document}\n\n7.2 Limits and Continuity of Functions of Several Variables 425\n\nProof d) Let $\\Gamma : I \\rightarrow E$ be a path that is a continuous mapping of an interval\n$[\uprho,\\beta]= I \\subset \\mathbb{R}$ such that $\\Gamma(\\uprho)= a, \\Gamma(\\beta)= b$. By the connectedness of $E$ there\nexists such a path. The function $f \\circ \\Gamma : I \\rightarrow \\mathbb{R}$, being the composition of contin-\nuous functions, is continuous; therefore there is a point $\\gamma \\in[ \\uprho,\\beta]$ on the closed\ninterval $[\uprho,\\beta]$ at which $f \\circ \\Gamma(\\gamma)= C$. Set $c = \\Gamma(\\gamma)$. Then $c \\in E$ and $f(c)= C$.$\\Box$\n\n\\noindent\\textbf{Example 12} The sphere $S(0;r)$ de\u2019ned in $\\mathbb{R}^m$ by the equation\n$$\n(x_1)^2 +\\cdots+ (x_m)^2 = r^2,\n$$\nis a compact set.\n\nIndeed, it follows from the continuity of the function\n$$(x_1,\\ldots,x_m) \\mapsto (x_1)^2 +\\cdots+ (x_m)^2$$\nthat the sphere is closed, and from the fact that $|x_i |\\leq r$ ($i = 1,\\ldots,m $) on the sphere\nthat it is bounded.\n\nThe function\n$$(x_1,\\ldots,x_m) \\mapsto (x_1)^2 +\\cdots+ (x_k )^2 - (x_{k+1})^2 -\\cdots- (x_m)^2$$\nis continuous on all of $\\mathbb{R}^m$, so that its restriction to the sphere is also continuous,\nand by the global property c) of continuous functions assumes its minimal and max-\nimal values on the sphere. At the points $(1, 0,\\ldots,0)$ and $(0,\\ldots, 0, 1)$ this function\nassumes the values $1$ and $-1$ respectively. By the connectedness of the sphere (see\nProblem 3 at the end of this section), global property d) of continuous functions now\nenables us to assert that there is a point on the sphere where this function assumes\nthe value $0$.\n\n\\noindent\\textbf{Example 13} The open set $\\mathbb{R}^m\\setminus S(0;r)$ for $r> 0$ is not a domain, since it is not\nconnected.\n\nIndeed, if $\\Gamma : I \\rightarrow \\mathbb{R}^m$ is a path one end of which is at the point $x_0 = (0,\\ldots,0)$\nand the other at some point $x_1 = (x_1^1,\\ldots,x_m^1 )$ such that $(x_1^1)^2 +\\cdots+ (x_m^1 )^2 >r^2$, \nthen the composition of the continuous functions $\\Gamma : I \\rightarrow \\mathbb{R}^m$ and $f : \\mathbb{R}^m \\rightarrow \\mathbb{R}$,\nwhere\n$$(x_1,\\ldots,x_m) \\ f \\mapsto (x_1)^2 +\\cdots+ (x_m)^2,$$\nis a continuous function on $I$ assuming values less than $r^2$ at one endpoint and\ngreater than $r^2$ at the other. Hence there is a point $\\gamma$ on $I$ at which $(f \\circ \\Gamma )(\\gamma )= r^2$.\nThen the point $x_{\\gamma} = \\Gamma(\\gamma)$ in the support of the path turns out to lie on the sphere\n$S(0;r)$. We have thus shown that it is impossible to get out of the ball $B(0;r) \\subset \\mathbb{R}^m$\nwithout intersecting its boundary sphere $S(0;r)$.\n\n\\end{document}"
}