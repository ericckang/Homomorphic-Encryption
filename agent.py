import os
import time
import requests
import tenseal as ts

SHARED_DIR = "./he_shared"
os.makedirs(SHARED_DIR, exist_ok=True)
SERVER_URL = "http://localhost:8080/compute"

def get_optimal_params(scheme, vector_size):
    """
    Dynamic Parameter Upgrader with Hard Limits (Cost Evaluator).
    Prevents the 2GB Protobuf crash by capping the polynomial modulus degree.
    """
    if scheme == "BFV":
        if vector_size <= 4096: return 4096
        else: return 8192 # Hard cap
    elif scheme == "CKKS":
        return 16384 # Minimum 16384 needed for depth-3 multiplication

def run_salary_benchmark_demo(vector_size):
    print("\n" + "="*70)
    print(f" SCENARIO 1: BFV Scheme (Batch Size: {vector_size})")
    print("="*70)
    
    poly_mod_degree = get_optimal_params("BFV", vector_size)
    print(f"[Agent] Dynamic Params -> Selected BFV poly_modulus_degree: {poly_mod_degree}")
    
    context = ts.context(ts.SCHEME_TYPE.BFV, poly_modulus_degree=poly_mod_degree, plain_modulus=1032193)
    # SAFETY FIX: Omit Galois keys to save hundreds of MBs in context size
    context.generate_relin_keys()

    context_path = os.path.join(SHARED_DIR, "bfv_context.bin")
    with open(context_path, "wb") as f:
        f.write(context.serialize(save_secret_key=False))

    user_salaries = [85000 + i for i in range(vector_size)]
    print(f"[Agent] Encrypting array of {vector_size} integers...")
    
    t0 = time.time()
    encrypted_salary = ts.bfv_vector(context, user_salaries)
    encryption_time = time.time() - t0

    payload_path = os.path.join(SHARED_DIR, "salary_payload.bin")
    with open(payload_path, "wb") as f:
        f.write(encrypted_salary.serialize())
    
    payload_size_kb = os.path.getsize(payload_path) / 1024

    print("[Agent] Sending ciphertext payload to Compute Service...")
    res = requests.post(SERVER_URL, json={
        "computation_type": "salary_benchmark",
        "context_path": context_path,
        "payload_path": payload_path,
        "result_path": os.path.join(SHARED_DIR, "salary_result.bin")
    })
    
    if res.status_code != 200:
        print(f"\n[Agent] ❌ Server returned error (HTTP {res.status_code}): {res.text}")
        return

    try:
        response_data = res.json()
    except Exception:
        print("\n[Agent] ❌ Failed to parse server response.")
        return
    
    if response_data.get("status") == "success":
        eval_time = response_data.get("evaluation_time_sec")

        with open(response_data.get("result_path"), "rb") as f:
            encrypted_result = ts.bfv_vector_from(context, f.read())
        
        decrypted = encrypted_result.decrypt()
        print(f"[Agent] First result sample: {decrypted[0]}")
        
        print("\n📊 BFV BENCHMARK REPORT (LIGHT COMPUTATION)")
        print(f" Data Array Size  : {vector_size} elements")
        print(f" Poly Mod Degree  : {poly_mod_degree}")
        print(f" Ciphertext Size  : {payload_size_kb:.2f} KB")
        print(f" Encryption Time  : {encryption_time:.4f} sec")
        print(f" Evaluation Time  : {eval_time:.4f} sec")

def run_medical_risk_demo(vector_size):
    print("\n" + "="*70)
    print(f" SCENARIO 2: HEAVY CKKS Scheme (Batch Size: {vector_size})")
    print("="*70)
    
    poly_mod_degree = get_optimal_params("CKKS", vector_size)
    print(f"[Agent] Dynamic Params -> Selected CKKS poly_modulus_degree: {poly_mod_degree}")
    
    coeff_mod_bit_sizes = [60, 40, 40, 40, 40, 60]
    context = ts.context(ts.SCHEME_TYPE.CKKS, poly_modulus_degree=poly_mod_degree, coeff_mod_bit_sizes=coeff_mod_bit_sizes)
    context.global_scale = 2**40
    
    print("[Agent] Generating optimized cryptographic keys (Galois omitted)...")
    context.generate_relin_keys()

    context_path = os.path.join(SHARED_DIR, "ckks_context.bin")
    with open(context_path, "wb") as f:
        f.write(context.serialize(save_secret_key=False))

    patient_metrics = [1.05 + (i*0.0001) for i in range(vector_size)]
    print(f"[Agent] Encrypting array of {vector_size} floats...")
    
    t0 = time.time()
    encrypted_metrics = ts.ckks_vector(context, patient_metrics)
    encryption_time = time.time() - t0

    payload_path = os.path.join(SHARED_DIR, "medical_payload.bin")
    with open(payload_path, "wb") as f:
        f.write(encrypted_metrics.serialize())
    
    payload_size_kb = os.path.getsize(payload_path) / 1024

    print("[Agent] Sending deep ciphertext payload to Compute Service...")
    res = requests.post(SERVER_URL, json={
        "computation_type": "medical_risk",
        "context_path": context_path,
        "payload_path": payload_path,
        "result_path": os.path.join(SHARED_DIR, "medical_result.bin")
    })
    
    if res.status_code != 200:
        print(f"\n[Agent] ❌ Server returned error (HTTP {res.status_code}): {res.text}")
        return

    try:
        response_data = res.json()
    except Exception:
        print("\n[Agent] ❌ Failed to parse server response.")
        return
    
    if response_data.get("status") == "success":
        eval_time = response_data.get("evaluation_time_sec")

        with open(response_data.get("result_path"), "rb") as f:
            encrypted_result = ts.ckks_vector_from(context, f.read())
        
        decrypted = encrypted_result.decrypt()
        
        exact_score = (patient_metrics[0]**8) + (patient_metrics[0]**4) + (patient_metrics[0]**2)
        he_score = decrypted[0]
        error = abs(exact_score - he_score)

        print(f"[Agent] First result sample: {he_score:.4f}")
        print(f"[Agent] CKKS Approx Error: {error:.6f}")

        print("\n📊 CKKS BENCHMARK REPORT (DEEP COMPUTATION)")
        print(f" Data Array Size  : {vector_size} elements")
        print(f" Poly Mod Degree  : {poly_mod_degree}")
        print(f" Ciphertext Size  : {payload_size_kb:.2f} KB")
        print(f" Encryption Time  : {encryption_time:.4f} sec")
        print(f" Evaluation Time  : {eval_time:.4f} sec")

def run_error_scaling_test():
    print("\n" + "="*70)
    print(" SCENARIO 3: CKKS Error Scaling vs Multiplication Depth")
    print("="*70)
    
    # Needs a high degree to survive Depth-4 multiplication without Galois keys
    poly_mod_degree = 32768
    coeff_mod_bit_sizes = [60, 40, 40, 40, 40, 40, 60] 
    
    print(f"[Agent] Initializing MAX Context for Depth-4 test (degree={poly_mod_degree})...")
    context = ts.context(ts.SCHEME_TYPE.CKKS, poly_modulus_degree=poly_mod_degree, coeff_mod_bit_sizes=coeff_mod_bit_sizes)
    context.global_scale = 2**40
    
    context.generate_relin_keys()

    context_path = os.path.join(SHARED_DIR, "ckks_scaling_context.bin")
    with open(context_path, "wb") as f:
        f.write(context.serialize(save_secret_key=False))

    vector_size = 100 # Keep batch size small for pure mathematical error tracking
    base_value = 1.05
    patient_metrics = [base_value + (i*0.0001) for i in range(vector_size)]
    
    encrypted_metrics = ts.ckks_vector(context, patient_metrics)
    payload_path = os.path.join(SHARED_DIR, "scaling_payload.bin")
    with open(payload_path, "wb") as f:
        f.write(encrypted_metrics.serialize())
    
    print("[Agent] Sending ciphertext to Compute Service to measure scaling...")
    res = requests.post(SERVER_URL, json={
        "computation_type": "ckks_error_scaling",
        "context_path": context_path,
        "payload_path": payload_path,
        "result_path": os.path.join(SHARED_DIR, "scaling_result.bin")
    })
    
    if res.status_code != 200:
        print(f"\n[Agent] ❌ Server returned error: {res.text}")
        return

    response_data = res.json()
    if response_data.get("status") == "success":
        base_path = response_data.get("result_path")
        
        print("\n📊 CKKS ERROR SCALING REPORT")
        print(f"{'Depth':<10} | {'Exact Value':<15} | {'HE Value':<15} | {'Absolute Error':<15}")
        print("-" * 65)

        for depth_idx, power in enumerate([2, 4, 8, 16], start=1):
            file_path = f"{base_path}_d{depth_idx}.bin"
            
            with open(file_path, "rb") as f:
                encrypted_result = ts.ckks_vector_from(context, f.read())
            
            decrypted = encrypted_result.decrypt()
            
            exact_val = patient_metrics[0] ** power
            he_val = decrypted[0]
            error = abs(exact_val - he_val)
            
            print(f"Depth {depth_idx:<4} | {exact_val:<15.6f} | {he_val:<15.6f} | {error:.8f}")

if __name__ == "__main__":
    print("\n" + "#"*70)
    print(" Homomorphic Encryption (HE) Skill Demonstrator - Full Suite")
    print("#"*70)
    
    try:
        user_input = input("\nEnter the desired Batch Size (e.g., 100, 4000, 40000): ")
        vector_size = int(user_input.strip())
        if vector_size <= 0:
            raise ValueError
    except ValueError:
        print("[Agent] Invalid input. Defaulting to 4000.")
        vector_size = 4000

    # 1. BFV Test
    run_salary_benchmark_demo(vector_size)
    time.sleep(1)
    
    # 2. CKKS Heavy Test
    run_medical_risk_demo(vector_size)
    time.sleep(1)
    
    # 3. CKKS Error Scaling Test
    run_error_scaling_test()