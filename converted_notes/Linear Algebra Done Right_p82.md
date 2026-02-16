---
title: Note from Linear Algebra Done Right (p. 82)
author: Sheldon Axler
date: 2026-02-09 21:20
tags: [auto-note, Linear Algebra Done Right]
---

62 Chapter 3 Linear Maps

3.19 definition: surjective
A function $T\colon V \to W$ is called surjective if its range equals $W$.

To illustrate the definition above, note that of the ranges we computed in 3.17,
only the differentiation map is surjective (except that the zero map is surjective in
the special case $W = \{0\}$).

Some people use the term onto, which
means the same as surjective.

Whether a linear map is surjective de-
pends on what we are thinking of as the
vector space into which it maps.

3.20 example: surjectivity depends on the target space
The differentiation map $D \in \mathcal{L}(\mathcal{P}_5(\mathbf{R}))$ defined by $Dp = p'$ is not surjective,
because the polynomial $x^5$ is not in the range of $D$. However, the differentiation
map $S \in \mathcal{L}(\mathcal{P}_5(\mathbf{R}), \mathcal{P}_4(\mathbf{R}))$ defined by $Sp = p'$ is surjective, because its range
equals $\mathcal{P}_4(\mathbf{R})$, which is the vector space into which $S$ maps.

Fundamental Theorem of Linear Maps
The next result is so important that it gets a dramatic name.

3.21 fundamental theorem of linear maps
Suppose $V$ is finite-dimensional and $T \in \mathcal{L}(V, W)$. Then range $T$ is finite-
dimensional and
$$
dim V = \operatorname{dim} \operatorname{null} T + \operatorname{dim} \operatorname{range} T.
$$
Proof Let $u_1, \dots, u_m$ be a basis of $\operatorname{null} T$; thus $\operatorname{dim} \operatorname{null} T = m$. The linearly
independent list $u_1, \dots, u_m$ can be extended to a basis
$$
u_1, \dots, u_m, v_1, \dots, v_n$$
of $V$ (by 2.32). Thus $\operatorname{dim} V = m + n$. To complete the proof, we need to show that
range $T$ is finite-dimensional and $\operatorname{dim} \operatorname{range} T = n$. We will do this by proving
that $Tv_1, \dots, Tv_n$ is a basis of range $T$.

Let $v \in V$. Because $u_1, \dots, u_m, v_1, \dots, v_n$ spans $V$, we can write
$$v = a_1 u_1 + \cdots + a_m u_m + b_1 v_1 + \cdots + b_n v_n,$$
where the $a$’s and $b$’s are in $\mathbf{F}$. Applying $T$ to both sides of this equation, we get
$$Tv = b_1 Tv_1 + \cdots + b_n Tv_n,$$
where the terms of the form $Tu_k$ disappeared because each $u_k$ is in $\operatorname{null} T$. The
last equation implies that the list $Tv_1, \dots, Tv_n$ spans range $T$. In particular, range $T$
is finite-dimensional.