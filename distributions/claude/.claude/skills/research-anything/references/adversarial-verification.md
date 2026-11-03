# Adversarial & Boundary Verification Playbooks (Stage 3)

In **RA (`research-anything`)**, standard AI "unit tests" (happy-path assertions that confirm the model's own assumptions) are **worthless**. Passing a basic test only proves that the code runs on a toy input—it does **not** prove that the invention actually works.

**Stage 3 requires you to act as an adversary trying to destroy your own prototype.** If your breaking test does not find a failure boundary or extreme stress limit, your test is too weak.

---

## Universal Adversarial Verification Rules

1. **No Mocking the Core Mechanism**: Never mock, stub, or simplify the mathematical, physical, or algorithmic core being tested.
2. **Push Until It Breaks (Boundary Mapping)**: Sweep parameters (scale, noise, step count, temperature, frequency, dimensionality) across orders of magnitude until you locate the exact breakdown threshold.
3. **Structural Prevention over Symptom Patching**: When you discover what breaks the prototype, do not add a special-case `if` guard. Modify the underlying equation, invariant, topology, or architecture so that class of failure is structurally prevented.

---

## Domain-Specific Breaking Playbooks

### 1. Machine Learning, Neural Networks & Novel Architectures
- **Gradient Flow & Numerical Stability**:
  - Verify non-zero, non-exploding gradients across **every** learnable parameter (`0 < ||grad|| < threshold`).
  - Test deep stacking / recurrent rollout over $10^3 - 10^4$ steps to detect vanishing/exploding activations or floating-point drift.
- **Degenerate & Pathological Inputs**:
  - Zero tensors, constant tensors, high-variance spikes, NaN/Inf boundary probes, batch size = 1, prime/unaligned sequence lengths.
- **Generalization vs. Memorization Probe**:
  - Test on **out-of-distribution (OOD)** shifts, permuted token/feature orderings, and extrapolate beyond training sequence length/scale.
  - Verify the network cannot solve the task when target labels are randomized in a control sanity check (or verify how capacity scales).
- **Ablation Proof**:
  - Disable or identity-replace the novel component and prove empirically that performance/convergence degrades without it.

### 2. Novel Algorithms, Frameworks & Game Mechanics
- **Pathological Topologies & Edge Inputs**:
  - Cyclic graphs, disconnected components, adversarial worst-case sorting/hashing distributions, degenerate zero-area/collinear geometries.
- **Long-Horizon State Invariant Drift**:
  - Simulate $10,000+$ ticks/frames of randomized and adversarial state transitions. Verify conservation laws, state synchronization, memory bounds, and determinism.
- **Scale & Concurrency Stress**:
  - Measure empirical time/space complexity across $N = 10, 10^2, 10^3, 10^4, 10^5$ to verify asymptotic behavior matches theoretical claims.

### 3. Custom Encryption, Hashing & Security Primitives
- **Avalanche & Diffusion Test**:
  - Flip 1 bit in the input/key across $10,000$ random trials; verify output bit-flip probability is centered at $50\% \pm \epsilon$ with no dead bit positions.
- **Statistical Bias & Entropy Suite**:
  - Run byte-frequency, chi-square, serial correlation, and run-length tests on ciphertext/output streams generated from low-entropy plaintexts (e.g., all zeros, repeating patterns).
- **Differential & Chosen-Input Probing**:
  - Feed related inputs ($P, P \oplus \Delta$) and verify zero detectable correlation in output differences.
- **Invertibility & Collision Hunting**:
  - Prove round-trip lossless decryption ($D_k(E_k(P)) == P$) across boundary bit lengths, and birthday-bound collision resistance on reduced-bit variants.

### 4. Hardware / CPU Re-Positioning, Thermal & System Layouts
- **Worst-Case Workload & Thermal Envelope**:
  - Simulate sustained peak power density (TDP spikes), asymmetric core/unit loading, and transient current ($dI/dt$) droop.
- **Signal Integrity & Latency Bounds**:
  - Verify critical-path wirelength, propagation delay, clock skew, and crosstalk under worst-case routing congestion.
- **Geometric & Manufacturing Constraints**:
  - Check keep-out zones, minimum pitch/clearance violations, aspect-ratio extremes, and pin/pad accessibility.

### 5. New Materials, Lab Data Analysis & Physical Systems
- **Conservation & Physical Law Audits**:
  - Verify mass, energy, charge, momentum, and thermodynamic entropy constraints across the entire operating domain.
- **Sensitivity & Perturbation Analysis**:
  - Inject realistic sensor noise, impurity variance, and temperature/pressure fluctuations ($\pm 1\%, \pm 5\%, \pm 20\%$) to test whether the predicted property is stable or a razor-thin mathematical artifact.
- **Cross-Validation Against Ground-Truth Library**:
  - Compare boundary behavior against known reference materials/laws in `research/library/` at limiting regimes ($T \to 0$, $P \to \infty$, concentration $\to 0$).

### 6. Redesigning Shapes, Geometries & Mathematical Objects
- **Singularity & Degeneracy Stress**:
  - Test extreme aspect ratios, sharp curvature spikes, self-intersection boundaries, non-manifold edges, and topological genus transitions.
- **Invariance Verification**:
  - Verify expected behavior under rigid transformations (rotation, translation, reflection), uniform/non-uniform scaling, and discretization mesh resolution changes.
