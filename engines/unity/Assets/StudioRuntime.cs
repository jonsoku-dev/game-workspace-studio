using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using UnityEngine;

[Serializable] public class StudioPin { public string path, sha256; }
[Serializable] public class StudioIntegrity { public StudioPin[] files; }

[Serializable] public class StudioFrame { public StudioRect rect; public float duration_ms; }
[Serializable] public class StudioRect { public float x, y, w, h; }
[Serializable] public class StudioClip { public string name; public bool loop; public float duration_ms; public StudioFrame[] frames; }
[Serializable] public class StudioEvent { public string action, sheet; public float start_ms, duration_ms; public float[] pivot, at_px; public StudioFrame[] frames; }
[Serializable] public class StudioParticle { public float[] offset, drift, spin; public float start_s, life_s, scale; }
[Serializable] public class StudioEffect { public float duration_s; public StudioParticle[] particles; }
[Serializable] public class StudioAsset { public string id, atlas, mesh; public float[] cell_size, pivot; public StudioClip[] clips; public StudioEvent[] events; public StudioEffect effect; }
[Serializable] public class StudioNode { public string id, asset, parent, action; public float[] position, rotation_degrees, scale; public float size_m; }
[Serializable] public class StudioScene { public StudioNode[] nodes; }
[Serializable] public class StudioProduct { public StudioScene scene; public StudioAsset[] assets; }
[Serializable] public class StudioProducts { public StudioProduct[] products; }
[Serializable] public class StudioMesh { public StudioPart[] parts; }
[Serializable] public class StudioPart { public string name, texture; public Vector3[] vertices, normals; public Vector2[] uv; public int[] triangles; public float[] color, emission; public float metallic, roughness; }

public class StudioRuntime : MonoBehaviour
{
    public static string Root => Path.Combine(Application.streamingAssetsPath, "Studio");
    public readonly List<StudioSprite> Sprites = new List<StudioSprite>();
    public readonly List<StudioParticles> Effects = new List<StudioParticles>();
    public static T Read<T>(string relative) => JsonUtility.FromJson<T>(File.ReadAllText(Path.Combine(Root, relative)));
    public static Vector3 Position(float[] v) => new Vector3(v[0], v[1], -v[2]);
    public static Vector3 Scale(float[] v) => new Vector3(v[0], v[1], v[2]);
    public static Quaternion Rotation(float[] degrees) =>
        Quaternion.AngleAxis(-degrees[0], Vector3.right) *
        Quaternion.AngleAxis(-degrees[1], Vector3.up) *
        Quaternion.AngleAxis(degrees[2], Vector3.forward);
    public static Texture2D Texture(string relative)
    {
        var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
        if (!ImageConversion.LoadImage(texture, File.ReadAllBytes(Path.Combine(Root, relative))))
            throw new InvalidDataException("Texture failed " + relative);
        texture.filterMode = FilterMode.Point;
        texture.wrapMode = TextureWrapMode.Clamp;
        return texture;
    }
    static Color ColorOf(float[] c) => new Color(c[0], c[1], c[2], c[3]);
    public static GameObject Model(string relative)
    {
        var root = new GameObject("Model");
        foreach (var p in Read<StudioMesh>(relative).parts)
        {
            var child = new GameObject(p.name);
            child.transform.SetParent(root.transform, false);
            var mesh = new Mesh { indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
            mesh.vertices = p.vertices; mesh.normals = p.normals; mesh.uv = p.uv; mesh.triangles = p.triangles;
            mesh.RecalculateBounds();
            child.AddComponent<MeshFilter>().sharedMesh = mesh;
            var shader = Shader.Find("Standard");
            if (shader == null) throw new InvalidOperationException("Built-in Standard shader required");
            var material = new Material(shader) { color = ColorOf(p.color) };
            material.SetFloat("_Metallic", p.metallic);
            material.SetFloat("_Glossiness", 1 - p.roughness);
            material.SetColor("_EmissionColor", ColorOf(p.emission));
            material.EnableKeyword("_EMISSION");
            if (!string.IsNullOrEmpty(p.texture))
                material.mainTexture = Texture(Path.Combine(Path.GetDirectoryName(relative), p.texture));
            child.AddComponent<MeshRenderer>().sharedMaterial = material;
        }
        return root;
    }
    public static void VerifyIntegrity()
    {
        foreach (var pin in Read<StudioIntegrity>("integrity.json").files)
        {
            using (var sha = SHA256.Create())
            {
                var hash = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(Path.Combine(Root, pin.path)))).Replace("-", "").ToLowerInvariant();
                if (hash != pin.sha256) throw new InvalidDataException("Pinned payload drift " + pin.path);
            }
        }
    }
    void Start()
    {
        if (GetComponent<StudioGame>() == null) Reload();
    }
    public void Reload()
    {
        while (transform.childCount > 0) DestroyImmediate(transform.GetChild(0).gameObject);
        Sprites.Clear(); Effects.Clear(); Load();
    }
    public void Load()
    {
        VerifyIntegrity();
        foreach (var product in Read<StudioProducts>("products.json").products)
        {
            var nodes = new Dictionary<string, GameObject>();
            var specs = new Dictionary<string, StudioAsset>();
            foreach (var asset in product.assets) specs.Add(asset.id, asset);
            foreach (var node in product.scene.nodes)
            {
                var anchor = new GameObject(node.id);
                nodes.Add(node.id, anchor);
                var asset = specs[node.asset];
                if (!string.IsNullOrEmpty(asset.mesh))
                {
                    if (asset.effect != null && asset.effect.particles != null)
                    {
                        var particles = anchor.AddComponent<StudioParticles>();
                        particles.Build(asset); Effects.Add(particles);
                    }
                    else Model(asset.mesh).transform.SetParent(anchor.transform, false);
                }
                else
                {
                    var sprite = anchor.AddComponent<StudioSprite>();
                    sprite.Build(asset, node.size_m > 0 ? node.size_m : 1);
                    sprite.Play(string.IsNullOrEmpty(node.action) ? asset.clips[0].name : node.action);
                    Sprites.Add(sprite);
                }
            }
            foreach (var node in product.scene.nodes)
            {
                var t = nodes[node.id].transform;
                t.SetParent(string.IsNullOrEmpty(node.parent) ? transform : nodes[node.parent].transform, false);
                t.localPosition = Position(node.position); t.localRotation = Rotation(node.rotation_degrees); t.localScale = Scale(node.scale);
            }
        }
        Sample(0);
    }
    public void Sample(float seconds)
    {
        foreach (var sprite in Sprites) sprite.Sample(seconds * 1000);
        foreach (var effect in Effects) effect.Sample(seconds);
    }
    void Update() => Sample(Time.timeSinceLevelLoad);
}

public class StudioParticles : MonoBehaviour
{
    StudioEffect recipe;
    readonly List<Transform> particles = new List<Transform>();
    public int Count => particles.Count;
    public void Build(StudioAsset asset)
    {
        recipe = asset.effect;
        var prototype = StudioRuntime.Model(asset.mesh);
        foreach (var p in recipe.particles)
        {
            var model = Instantiate(prototype, transform, false);
            particles.Add(model.transform);
        }
        DestroyImmediate(prototype);
    }
    public void Sample(float seconds)
    {
        for (int i = 0; i < particles.Count; i++)
        {
            var p = recipe.particles[i]; var t = particles[i];
            float age = Mathf.Repeat(seconds - p.start_s, recipe.duration_s);
            t.gameObject.SetActive(age < p.life_s);
            t.localPosition = StudioRuntime.Position(p.offset) + StudioRuntime.Position(p.drift) * age;
            t.localRotation = StudioRuntime.Rotation(new[] { p.spin[0] * age * Mathf.Rad2Deg, p.spin[1] * age * Mathf.Rad2Deg, p.spin[2] * age * Mathf.Rad2Deg });
            t.localScale = Vector3.one * Mathf.Max(0.001f, p.scale * Mathf.Sin(Mathf.PI * Mathf.Clamp01(age / p.life_s)));
        }
    }
}

public class StudioSprite : MonoBehaviour
{
    StudioAsset asset;
    StudioClip clip;
    SpriteRenderer renderer2d;
    readonly Dictionary<string, Sprite[]> actions = new Dictionary<string, Sprite[]>();
    readonly List<SpriteRenderer> eventRenderers = new List<SpriteRenderer>();
    readonly List<Sprite[]> eventFrames = new List<Sprite[]>();
    public string Action => clip.name;
    public int Frame { get; private set; }
    static Sprite[] Frames(Texture2D texture, StudioFrame[] frames, float[] pivot, float pixelsPerUnit)
    {
        var result = new Sprite[frames.Length];
        for (int i = 0; i < frames.Length; i++)
        {
            var r = frames[i].rect;
            result[i] = Sprite.Create(texture, new Rect(r.x, texture.height - r.y - r.h, r.w, r.h),
                new Vector2(pivot[0] / r.w, 1 - pivot[1] / r.h), pixelsPerUnit, 0, SpriteMeshType.FullRect);
        }
        return result;
    }
    public void Build(StudioAsset spec, float size)
    {
        asset = spec; renderer2d = gameObject.AddComponent<SpriteRenderer>();
        float ppu = spec.cell_size[1] / size;
        var texture = StudioRuntime.Texture(spec.atlas);
        foreach (var c in spec.clips) actions.Add(c.name, Frames(texture, c.frames, spec.pivot, ppu));
        foreach (var e in spec.events)
        {
            var child = new GameObject("Contact " + e.action);
            child.transform.SetParent(transform, false);
            child.transform.localPosition = new Vector3((e.at_px[0] - spec.pivot[0]) / ppu, (spec.pivot[1] - e.at_px[1]) / ppu, -0.001f);
            var renderer = child.AddComponent<SpriteRenderer>(); renderer.sortingOrder = 1;
            eventRenderers.Add(renderer); eventFrames.Add(Frames(StudioRuntime.Texture(e.sheet), e.frames, e.pivot, ppu));
        }
    }
    public void Play(string action)
    {
        clip = Array.Find(asset.clips, c => c.name == action);
        if (clip == null) throw new InvalidDataException("Unknown action " + action);
    }
    static int Index(StudioFrame[] frames, float ms)
    {
        for (int i = 0; i < frames.Length; i++) { ms -= frames[i].duration_ms; if (ms < 0) return i; }
        return frames.Length - 1;
    }
    public void Sample(float milliseconds)
    {
        float ms = clip.loop ? Mathf.Repeat(milliseconds, clip.duration_ms) : Mathf.Min(milliseconds, clip.duration_ms);
        Frame = Index(clip.frames, ms); renderer2d.sprite = actions[clip.name][Frame];
        for (int i = 0; i < asset.events.Length; i++)
        {
            var e = asset.events[i]; float age = ms - e.start_ms;
            eventRenderers[i].enabled = e.action == clip.name && age >= 0 && age < e.duration_ms;
            eventRenderers[i].sprite = eventFrames[i][Index(e.frames, Mathf.Max(0, age))];
        }
    }
}
