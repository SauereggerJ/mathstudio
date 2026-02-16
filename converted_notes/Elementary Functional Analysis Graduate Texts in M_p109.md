---
title: Note from Elementary Functional Analysis Graduate Texts in Mathematics (p. 109)
author: Barbara D. MacCluer
date: 2026-02-16 14:16
tags: [auto-note, Elementary Functional Analysis Graduate Texts in Mathematics]
---



## Page 109

4.7 Exercises 101

**Theorem 4.33.** If $T$ is compact in $B(H)$ and $\lambda$ is a nonzero value, then $\dim \ker (T - \lambda I) = \dim [\text{ran} (T - \lambda I)]^\perp$.

Theorem 4.32 is the case where the common value of the two numbers is zero. We do not give the proof of Theorem 4.33 here, but refer the interested reader to Lemma 3.2.8 in [2].

Every result in this section has an exact Banach space analogue, and only minor modiﬁcations need to be made to obtain the proofs in this more general setting. In particular Theorems 4.30 and 4.31 go through exactly as before. For Theorem 4.32, one need only pay attention to the fact that the adjoint is deﬁned slightly differently in the Banach space context, check that it is still true that $\ker A^* = (\text{ran} A)^\perp$, where now $M^\perp$ denotes the bounded linear functionals which are zero at each point of $M$, and recall that $(T - \lambda I)^* = T^* - \lambda I$.

## 4.7 Exercises

**4.1.** Suppose that $\|\cdot\|_{\alpha}$ and $\|\cdot\|_{\beta}$ are two equivalent norms on a vector space $X$. Show that if $(X, \|\cdot\|_{\alpha})$ is complete, then so is $(X, \|\cdot\|_{\beta})$.

**4.2.** Suppose that $X$ is an $n$-dimensional normed linear space over $\mathbb{C}$. Show that there is a linear bijection $T : X \to \mathbb{C}^n$ such that $T$ and $T^{-1}$ are continuous (in your choice of a norm for $\mathbb{C}^n$); in short, every $n$-dimensional normed linear space over $\mathbb{C}$ is isomorphic to $\mathbb{C}^n$.

**4.3.** Suppose that $X$ is a normed linear space, endowed with the metric topology, and suppose $X$ contains a nonempty open set $V$ such that $V$ is compact. The goal of this problem is to show that this forces $X$ to be ﬁnite-dimensional.

(a) Without loss of generality we may assume that $0\in V$. Show that as $x$ ranges over the set $V$, the open sets $x + \frac{1}{2}V \equiv\left\{ x + \frac{1}{2} v : v \in V \right\}$ form an open cover of $V$. B y compactness, extract a ﬁnite subcover $\left\{ x_k + \frac{1}{2}V \right\}_{k=1}^N$. Deﬁne $Y$ to be the span of the points $x_1, x_2, \dots, x_N$.

(b) Show that $V \subseteq Y + \frac{1}{2^j} V$ for each positive integer $j$, and hence $V \subseteq \bigcap_{j=1}^{\infty} (Y + \frac{1}{2^j} V)$.

(c) Show that $\bigcap_{j=1}^{\infty} (Y + \frac{1}{2^j} V)= Y $.