---
title: Note from Linear Algebra Done Right (p. 83)
author: Sheldon Axler
date: 2026-02-09 21:21
tags: [auto-note, Linear Algebra Done Right]
---

Section 3B Null Spaces and Ranges 63
To show $Tv_1, \dots, Tv_n$ is linearly independent, suppose $c_1, \dots, c_n \in \mathbf{F}$ and
$c_1Tv_1 + \cdots + c_nTv_n = 0$.
Then
$T(c_1v_1 + \cdots + c_nv_n) = 0$.
Hence
$c_1v_1 + \cdots + c_nv_n \in \text{null } T$.
Because $u_1, \dots, u_m$ spans $\text{null } T$, we can write
$c_1v_1 + \cdots + c_nv_n = d_1u_1 + \cdots + d_mu_m$,
where the $d$'s are in $\mathbf{F}$. This equation implies that all the $c$'s (and $d$'s) are 0
(because $u_1, \dots, u_m, v_1, \dots, v_n$ is linearly independent). Thus $Tv_1, \dots, Tv_n$ is linearly
independent and hence is a basis of range $T$, as desired.

Now we can show that no linear map from a finite-dimensional vector space
to a “smaller” vector space can be injective, where “smaller” is measured by
dimension.

3.22 linear map to a lower-dimensional space is not injective
Suppose $V$ and $W$ are finite-dimensional vector spaces such that
$\text{dim } V > \text{dim } W$. Then no linear map from $V$ to $W$ is injective.

Proof Let $T \in \mathcal{L}(V, W)$. Then
$\text{dim null } T = \text{dim } V - \text{dim range } T$
$\geq \text{dim } V - \text{dim } W$
$> 0$,
where the first line above comes from the fundamental theorem of linear maps
(3.21) and the second line follows from 2.37. The inequality above states that
$\text{dim null } T > 0$. This means that $\text{null } T$ contains vectors other than 0. Thus $T$ is
not injective (by 3.15).

3.23 example: linear map from $\mathbf{F}^4$ to $\mathbf{F}^3$ is not injective
Define a linear map $T\colon \mathbf{F}^4 \to \mathbf{F}^3$ by
$T(z_1, z_2, z_3, z_4) = (\sqrt{7}z_1 + \pi z_2 + z_4, 97z_1 + 3z_2 + 2z_3, z_2 + 6z_3 + 7z_4)$.
Because $\text{dim } \mathbf{F}^4 > \text{dim } \mathbf{F}^3$, we can use 3.22 to assert that $T$ is not injective, without
doing any calculations.