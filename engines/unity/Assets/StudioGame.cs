using System;
using UnityEngine;

public sealed class StudioGameState
{
    public readonly float[] TargetX = { -1, 0, 1 };
    public readonly float[] TargetZ = { 0.5f, 1.5f, 0.5f };
    public readonly bool[] Collected = new bool[3];
    public float X { get; private set; }
    public float Z { get; private set; }
    public float AttackAge { get; private set; }
    public bool Attacking { get; private set; }
    public bool Won => Collected[0] && Collected[1] && Collected[2];
    readonly float contactSeconds, attackSeconds;
    bool contacted;
    public StudioGameState(float contactSeconds, float attackSeconds)
    {
        if (contactSeconds <= 0 || attackSeconds <= contactSeconds) throw new ArgumentException("Invalid authored attack timing");
        this.contactSeconds = contactSeconds; this.attackSeconds = attackSeconds;
    }
    public void Reset()
    {
        X = Z = AttackAge = 0; Attacking = contacted = false;
        Array.Clear(Collected, 0, Collected.Length);
    }
    public void Step(float horizontal, float vertical, bool attack, bool reset, float seconds)
    {
        if (seconds < 0 || float.IsNaN(seconds) || float.IsInfinity(seconds)) throw new ArgumentOutOfRangeException(nameof(seconds));
        if (reset) { Reset(); return; }
        if (Won && !Attacking) return;
        if (attack && !Attacking) { Attacking = true; contacted = false; AttackAge = 0; }
        if (Attacking)
        {
            AttackAge += seconds;
            if (!contacted && AttackAge >= contactSeconds)
            {
                contacted = true;
                for (int i = 0; i < Collected.Length; i++)
                {
                    float dx = X - TargetX[i], dz = Z - TargetZ[i];
                    if (dx * dx + dz * dz <= 0.85f * 0.85f) Collected[i] = true;
                }
            }
            if (AttackAge >= attackSeconds) Attacking = false;
            return;
        }
        float length = (float)Math.Sqrt(horizontal * horizontal + vertical * vertical);
        if (length > 1) { horizontal /= length; vertical /= length; }
        X = Math.Max(-2, Math.Min(2, X + horizontal * seconds * 2));
        Z = Math.Max(-2, Math.Min(2, Z + vertical * seconds * 2));
    }
}

public class StudioGame : MonoBehaviour
{
    public StudioGameState State { get; private set; }
    StudioRuntime runtime;
    StudioSprite scout;
    GameObject[] targets;
    float clock;
    public void Initialize(StudioRuntime source)
    {
        runtime = source;
        var products = StudioRuntime.Read<StudioProducts>("products.json").products;
        StudioAsset spec = null;
        foreach (var product in products)
            foreach (var asset in product.assets)
                if (asset.id == "scout") spec = asset;
        if (spec == null) throw new InvalidOperationException("Sample requires the scout asset");
        var attack = Array.Find(spec.clips, c => c.name == "attack");
        var contact = Array.Find(spec.events, e => e.action == "attack");
        if (attack == null || contact == null) throw new InvalidOperationException("Sample requires authored attack/contact");
        State = new StudioGameState(contact.start_ms / 1000, attack.duration_ms / 1000);
        scout = runtime.Sprites.Find(s => s.gameObject.name == "scout-attack");
        if (scout == null) throw new InvalidOperationException("Sample requires scout-attack placement");
        runtime.enabled = false;
        targets = new GameObject[3];
        for (int i = 0; i < targets.Length; i++)
        {
            var mesh = new Mesh();
            mesh.vertices = new[] { new Vector3(0, 0.35f, 0), new Vector3(-0.15f, 0.15f, 0), new Vector3(0, 0.15f, -0.15f), new Vector3(0.15f, 0.15f, 0), new Vector3(0, 0.15f, 0.15f), Vector3.zero };
            mesh.triangles = new[] { 0, 1, 2, 0, 2, 3, 0, 3, 4, 0, 4, 1, 5, 2, 1, 5, 3, 2, 5, 4, 3, 5, 1, 4 };
            mesh.RecalculateNormals();
            var target = new GameObject("Crystal " + (i + 1));
            target.transform.SetParent(transform, false);
            target.transform.position = new Vector3(State.TargetX[i], 0, State.TargetZ[i]);
            target.AddComponent<MeshFilter>().sharedMesh = mesh;
            var material = new Material(Shader.Find("Standard")); material.color = new Color(0.3f, 0.85f, 1);
            target.AddComponent<MeshRenderer>().sharedMaterial = material;
            targets[i] = target;
        }
        Step(0, 0, false, true, 0);
    }
    void Start()
    {
        var source = GetComponent<StudioRuntime>();
        source.Reload(); Initialize(source);
    }
    public void Step(float horizontal, float vertical, bool attack, bool reset, float seconds)
    {
        State.Step(horizontal, vertical, attack, reset, seconds);
        clock = reset ? 0 : clock + seconds;
        runtime.Sample(clock);
        scout.transform.position = new Vector3(State.X, 0, State.Z);
        scout.Play(State.Attacking ? "attack" : !State.Won && (horizontal != 0 || vertical != 0) ? "walk" : "idle");
        scout.Sample(State.Attacking ? State.AttackAge * 1000 : clock * 1000);
        for (int i = 0; i < targets.Length; i++) targets[i].SetActive(!State.Collected[i]);
    }
    void Update()
    {
        float horizontal = (Input.GetKey(KeyCode.D) ? 1 : 0) - (Input.GetKey(KeyCode.A) ? 1 : 0);
        float vertical = (Input.GetKey(KeyCode.W) ? 1 : 0) - (Input.GetKey(KeyCode.S) ? 1 : 0);
        Step(horizontal, vertical, Input.GetKeyDown(KeyCode.Space), Input.GetKeyDown(KeyCode.R), Time.deltaTime);
    }
    void OnGUI()
    {
        if (State == null) return;
        int count = 0; foreach (bool collected in State.Collected) if (collected) count++;
        GUI.Label(new Rect(16, 16, 600, 30), State.Won ? "All crystals collected. Press R to reset." : "WASD move | Space attack | R reset | Crystals " + count + "/3");
    }
}
