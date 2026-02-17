---
title: Note from Mathematical Analysis I (pp. 423-424)
author: V. A. Zorich
date: 2026-02-17 19:56
tags: [auto-note, Mathematical Analysis I]
---



## Page 423

6.5 Improper Integrals 403

**Example 12** Using Remark 1, by the formula for integration by parts in an improper integral, we find that
$$\int_{\pi/2}^{+\infty} \frac{\sin x}{x} dx = -\frac{\cos x}{x}\bigg\bigg|_{\pi/2}^{+\infty} - \int_{\pi/2}^{+\infty} \frac{\cos x}{x^2} dx = -\int_{\pi/2}^{+\infty} \frac{\cos x}{x^2} dx,$$
provided the last integral converges. But, as we saw in Example 5, this integral converges, and hence the integral
$$\int_{\pi/2}^{+\infty} \frac{\sin x}{x} dx \quad (6.77)$$
also converges.

At the same time, the integral (6.77) is not absolutely convergent. Indeed, for $b \in [ \pi/2, +\infty[$ we have
$$\int_{\pi/2}^{b} \left|\frac{\sin x}{x}\right| dx \ge \int_{\pi/2}^{b} \frac{\sin^2 x}{x} dx = \frac{1}{2} \int_{\pi/2}^{b} \frac{dx}{x} - \frac{1}{2} \int_{\pi/2}^{b} \frac{\cos 2x}{x} dx. \quad (6.78)$$
The integral
$$\int_{\pi/2}^{+\infty} \frac{\cos 2x}{x} dx,$$ 
as can be verified through integration by parts, is convergent, so that as $b \to +\infty$, the difference on the right-hand side of relation (6.78) tends to $+\infty$. Thus, by estimate (6.78), the integral (6.77) is not absolutely convergent.

We now give a special convergence test for improper integrals based on the second mean-value theorem and hence essentially on the same formula for integration by parts.

**Proposition 4 (Abel–Dirichlet test for convergence of an integral)** Let $x \mapsto f(x)$ and $x \mapsto g(x)$ be functions defined on an interval $[a,\omega [$ and integrable on every closed interval $[a,b ]\subset[ a,\omega [$. Suppose that $g$ is monotonic.

Then a sufficient condition for convergence of the improper integral
$$\int_{a}^{\omega} (f \cdot g)(x) dx \quad (6.79)$$
is that the one of the following pairs of conditions hold:

$\alpha 1)$ the integral $\int_{a}^{\omega} f(x)dx$ converges, $\beta 1)$ the function $g$ bounded on $[a,\omega [$,

or

$\alpha 2)$ the function $F(b) = \int_{a}^{b} f(x)dx$ is bounded on $[a,\omega [$, $\beta 2)$ the function $g(x)$ tends to zero as $x \to \omega$, $x \in[ a,\omega [$.

## Page 424

{
  "markdown": "Proof For any $b_1$ and $b_2$ in $[\alpha,\\omega [$ we have, by the second mean-value theorem,\n$$\\int_{b_1}^{b_2} (f \\cdot g)(x) dx = g(b_1) \\int_{b_1}^{\\xi} f(x)dx + g(b_2) \\int_{\\xi}^{b_2} f(x)dx,$$\nwhere $\\xi$ is a point lying between $b_1$ and $b_2$. Hence by the Cauchy convergence criterion (Proposition 2), we conclude that the integral (6.79) does indeed converge if either of the two pairs of conditions holds. $\\Box$\n\n### 6.5.3 Improper Integrals with More than One Singularity\n\nUp to now we have spoken only of improper integrals with one singularity caused either by the unboundedness of the function at one of the endpoints of the interval of integration or by an infinite limit of integration. In this subsection we shall show in what sense other possible variants of an improper integral can be taken.\n\nIf both limits of integration are singularities of either of these two types, then by definition\n$$\\int_{\\omega_1}^{\\omega_2} f(x)dx := \\int_{\\omega_1}^{c} f(x)dx + \\int_{c}^{\\omega_2} f(x)dx, \\quad (6.80)$$\nwhere $c$ is an arbitrary point of the open interval $] \\omega_1, \\omega_2 [$.\n\nIt is assumed here that each of the improper integrals on the right-hand side of (6.80) converges. Otherwise we say that the integral on the left-hand side of (6.80) diverges.\n\nBy Remark 2 and the additive property of the improper integral, the definition (6.80) is unambiguous in the sense that it is independent of the choice of the point $c \\in] \\omega_1, \\omega_2 [$.\n\n**Example 13**\n$$\\int_{-1}^{1} \\frac{dx}{\\sqrt{1 - x^2}} = \\int_{-1}^{0} \\frac{dx}{\\sqrt{1 - x^2}} + \\int_{0}^{1} \\frac{dx}{\\sqrt{1 - x^2}} = \\arcsin x \\Biggr|_{-1}^{0} + \\arcsin x \\Biggr|_{0}^{1} = \\arcsin x \\Biggr|_{−1}^{1} = \\pi.$$\n\n**Example 14** The integral\n$$\\int_{-\\infty}^{+\\infty} e^{-x^2} dx$$\nis called the Euler–Poisson integral, and sometimes the Gaussian integral. It obviously converges in the sense given above. It will be shown later that its value is $\\sqrt{\\pi}$.",
  "latex": "\\documentclass{article}\n\\usepackage{amsmath}\n\\usepackage{amssymb}\n\\begin{document}\n\nProof For any $b_1$ and $b_2$ in $[\\alpha,\\omega [$ we have, by the second mean-value theorem,\n$$\\int_{b_1}^{b_2} (f \\cdot g)(x) dx = g(b_1) \\int_{b_1}^{\\xi} f(x)dx + g(b_2) \\int_{\\xi}^{b_2} f(x)dx,$$ \nwhere $\\xi$ is a point lying between $b_1$ and $b_2$. Hence by the Cauchy convergence criterion (Proposition 2), we conclude that the integral (6.79) does indeed converge if either of the two pairs of conditions holds. \\hfill $\\Box$\n\n\\section*{6.5.3 Improper Integrals with More than One Singularity}\n\nUp to now we have spoken only of improper integrals with one singularity caused\neither by the unboundedness of the function at one of the endpoints of the interval\nof integration or by an infinite limit of integration. In this subsection we shall show\nin what sense other possible variants of an improper integral can be taken.\n\nIf both limits of integration are singularities of either of these two types, then by\ndefinition\n$$\\int_{\\omega_1}^{\\omega_2} f(x)dx := \\int_{\\omega_1}^{c} f(x)dx + \\int_{c}^{\\omega_2} f(x)dx, \\quad (6.80)$$\nwhere $c$ is an arbitrary point of the open interval $] \\omega_1, \\omega_2 [$.\n\nIt is assumed here that each of the improper integrals on the right-hand side of\n(6.80) converges. Otherwise we say that the integral on the left-hand side of ( 6.80)\ndiverges.\n\nBy Remark 2 and the additive property of the improper integral, the deﬁnition\n(6.80) is unambiguous in the sense that it is independent of the choice of the point\n$c \\in] \\omega_1, \\omega_2 [$.\n\n\\textbf{Example 13}\n$$\\int_{-1}^{1} \\frac{dx}{\\sqrt{1 - x^2}} = \\int_{-1}^{0} \\frac{dx}{\\sqrt{1 - x^2}} + \\int_{0}^{1} \\frac{dx}{\\sqrt{1 - x^2}} = \\arcsin x \\Biggr|_{-1}^{0} + \\arcsin x \\Biggr|_{0}^{1} = \\arcsin x \\Biggr|_{−1}^{1} = \\pi.$$\n\n\\textbf{Example 14} The integral\n$$\\int_{-\\infty}^{+\\infty} e^{-x^2} dx$$\nis called the Euler–Poisson integral, and sometimes the Gaussian integral. It obvi-\nously converges in the sense given above. It will be shown later that its value is $\\sqrt{\\pi}$.\n\n\\end{document}"
}