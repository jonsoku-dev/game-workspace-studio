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

public sealed class StudioGameFeedback
{
    readonly float contactSeconds;
    float x, z;
    int collected;
    bool moving, pendingContact, won;
    public StudioGameFeedback(float contactSeconds) { this.contactSeconds = contactSeconds; }
    public string Observe(StudioGameState state, bool attackStarted, bool reset)
    {
        int count = 0; foreach (bool value in state.Collected) if (value) count++;
        bool nowMoving = !reset && (state.X != x || state.Z != z);
        if (attackStarted) pendingContact = true;
        bool contact = pendingContact && state.AttackAge >= contactSeconds;
        if (contact || reset) pendingContact = false;
        string cue = reset ? "restart" : state.Won && !won ? "win" : count > collected ? "pickup"
            : contact ? "miss" : attackStarted ? "attack" : nowMoving && !moving ? "move"
            : !nowMoving && moving ? "stop" : "";
        x = state.X; z = state.Z; collected = count; won = state.Won; moving = nowMoving;
        return cue;
    }
}

public class StudioGame : MonoBehaviour
{
    public StudioGameState State { get; private set; }
    StudioRuntime runtime;
    StudioSprite scout;
    GameObject[] targets;
    float clock, cueSeconds;
    StudioGameFeedback feedback;
    bool paused, accents = true, reducedMotion;
    string cueText = "";
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
        feedback = new StudioGameFeedback(contact.start_ms / 1000);
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
        bool started = attack && !State.Attacking && !State.Won && !reset;
        State.Step(horizontal, vertical, attack, reset, seconds);
        cueSeconds = Mathf.Max(0, cueSeconds - seconds);
        string cue = feedback.Observe(State, started, reset);
        if (cue != "") Cue(cue);
        clock = reset ? 0 : clock + seconds;
        runtime.Sample(clock);
        scout.transform.position = new Vector3(State.X, 0, State.Z);
        scout.Play(State.Attacking ? "attack" : !State.Won && (horizontal != 0 || vertical != 0) ? "walk" : "idle");
        scout.Sample(State.Attacking ? State.AttackAge * 1000 : clock * 1000);
        for (int i = 0; i < targets.Length; i++) targets[i].SetActive(!State.Collected[i]);
    }
    void Cue(string kind)
    {
        switch (kind)
        {
            case "move": cueText = "Moving"; break;
            case "stop": cueText = "Stopped"; break;
            case "attack": cueText = "Swing"; break;
            case "miss": cueText = "Miss · move closer"; break;
            case "pickup": cueText = "Crystal collected"; break;
            case "win": cueText = "All crystals collected!"; break;
            case "restart": cueText = "Ready · collect three crystals"; break;
            case "pause": cueText = "Paused"; break;
            case "resume": cueText = "Resumed"; break;
            case "select": cueText = "Feedback setting changed"; break;
        }
        cueSeconds = accents ? 0.8f : 0;
    }
    void TogglePause()
    {
        paused = !paused;
        Cue(paused ? "pause" : "resume");
    }
    void ToggleAccents()
    {
        accents = !accents;
        Cue("select");
    }
    void ToggleMotion()
    {
        reducedMotion = !reducedMotion;
        Cue("select");
    }
    void Restart()
    {
        paused = false;
        Step(0, 0, false, true, 0);
    }
    void OnApplicationFocus(bool focused)
    {
        if (!focused && State != null && !paused) TogglePause();
    }
    void Update()
    {
        if (Input.GetKeyDown(KeyCode.P)) TogglePause();
        if (Input.GetKeyDown(KeyCode.F)) ToggleAccents();
        if (Input.GetKeyDown(KeyCode.V)) ToggleMotion();
        if (Input.GetKeyDown(KeyCode.R)) { Restart(); return; }
        if (paused) return;
        float horizontal = (Input.GetKey(KeyCode.D) ? 1 : 0) - (Input.GetKey(KeyCode.A) ? 1 : 0);
        float vertical = (Input.GetKey(KeyCode.W) ? 1 : 0) - (Input.GetKey(KeyCode.S) ? 1 : 0);
        Step(horizontal, vertical, Input.GetKeyDown(KeyCode.Space), false, Time.deltaTime);
    }
    void OnGUI()
    {
        if (State == null) return;
        int count = 0; foreach (bool collected in State.Collected) if (collected) count++;
        float width = Mathf.Min(420, Screen.width - 32);
        GUI.Box(new Rect(16, 16, width, 156), "Crystals " + count + "/3" + (paused ? " · PAUSED" : ""));
        GUI.Label(new Rect(24, 42, width - 16, 24), "WASD move | Space attack | R reset");
        if (GUI.Button(new Rect(24, 70, (width - 24) / 2, 26), paused ? "P · Resume" : "P · Pause")) TogglePause();
        if (GUI.Button(new Rect(24 + (width - 16) / 2, 70, (width - 24) / 2, 26), "R · Restart")) Restart();
        if (GUI.Button(new Rect(24, 102, (width - 24) / 2, 26), "F · Feedback " + (accents ? "on" : "off"))) ToggleAccents();
        if (GUI.Button(new Rect(24 + (width - 16) / 2, 102, (width - 24) / 2, 26), "V · Motion " + (reducedMotion ? "reduced" : "full"))) ToggleMotion();
        GUI.Label(new Rect(24, 138, width - 16, 24), State.Won ? "Complete! Press R to play again." : "Strike nearby crystals to collect them.");
        var camera = Camera.main;
        if (!accents || cueSeconds <= 0 || camera == null) return;
        Vector3 point = camera.WorldToScreenPoint(scout.transform.position + Vector3.up * 0.8f);
        if (point.z <= 0) return;
        float cueWidth = Mathf.Min(240, Screen.width - 16);
        float rise = reducedMotion ? 0 : (0.8f - cueSeconds) * 16;
        GUI.Box(new Rect(Mathf.Clamp(point.x - cueWidth / 2, 8, Screen.width - cueWidth - 8),
            Mathf.Clamp(Screen.height - point.y - rise, 180, Mathf.Max(180, Screen.height - 40)), cueWidth, 30), cueText);
    }
}
