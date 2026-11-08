using System;
using System.IO;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

[Serializable] public class StudioAcceptanceResult { public bool passed; public string engine, error; public string[] checks; }

public static class StudioBatch
{
    static readonly List<string> passedChecks = new List<string>();
    [MenuItem("Studio/Create Offline Scene")]
    public static void Create()
    {
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var runtime = new GameObject("Studio").AddComponent<StudioRuntime>();
        runtime.Load();
        var camera = new GameObject("Camera").AddComponent<Camera>();
        camera.tag = "MainCamera";
        camera.transform.position = new Vector3(1, 1.1f, -1.5f);
        camera.transform.LookAt(new Vector3(0.5f, 0.35f, 1));
        camera.nearClipPlane = 0.01f;
        var light = new GameObject("Key").AddComponent<Light>();
        light.type = LightType.Directional; light.transform.rotation = Quaternion.Euler(45, -35, 0);
        RenderSettings.ambientLight = new Color(0.35f, 0.35f, 0.35f);
        // Native meshes/materials are rebuilt from pinned StreamingAssets on each scene creation.
        Selection.activeGameObject = runtime.gameObject;
    }
    [MenuItem("Studio/Create Playable Sample")]
    public static void CreateGame()
    {
        Create();
        var runtime = UnityEngine.Object.FindFirstObjectByType<StudioRuntime>();
        runtime.gameObject.AddComponent<StudioGame>().Initialize(runtime);
        var camera = Camera.main;
        camera.orthographic = true; camera.orthographicSize = 2.8f;
        camera.transform.position = new Vector3(0, 3, -6);
        camera.transform.LookAt(new Vector3(0, 0.3f, 0.5f));
    }
    public static void Verify()
    {
        passedChecks.Clear();
        try
        {
            Create();
            var runtime = UnityEngine.Object.FindFirstObjectByType<StudioRuntime>();
            Require(runtime.Sprites.Count > 0 && runtime.Effects.Count > 0, "Supply sprite and particle products");
            var scout = runtime.Sprites[0];
            var spec = StudioRuntime.Read<StudioProducts>("products.json");
            int clips = 0;
            foreach (var product in spec.products)
                foreach (var asset in product.assets)
                    if (asset.clips != null)
                        foreach (var clip in asset.clips)
                        {
                            scout.Play(clip.name); clips++;
                            float elapsed = 0;
                            for (int i = 0; i < clip.frames.Length; i++)
                            {
                                scout.Sample(elapsed + 0.01f);
                                Require(scout.Frame == i, "Exact authored action boundary");
                                elapsed += clip.frames[i].duration_ms;
                            }
                        }
            Require(clips == 6, "Six action clips");
            scout.Play("attack"); scout.Sample(319);
            Require(!scout.transform.GetChild(0).GetComponent<SpriteRenderer>().enabled, "Contact absent before 320ms");
            scout.Sample(320);
            Require(scout.transform.GetChild(0).GetComponent<SpriteRenderer>().enabled, "Contact at 320ms");
            var effect = runtime.Effects[0];
            Require(effect.Count == 24 && effect.transform.parent.name == "camp-lantern", "24 parent-attached native particles");
            Require(Vector3.Distance(effect.transform.localPosition, new Vector3(0, 0.239f, 0)) < 0.00001f, "Local attachment coordinates");
            runtime.Sample(0.5f); var before = effect.transform.GetChild(0).localPosition;
            runtime.Sample(0.8f); Require(before != effect.transform.GetChild(0).localPosition, "Particles move");
            Require(runtime.GetComponentsInChildren<MeshFilter>(true).Length > 0, "Native drawable meshes");
            VerifyGame(runtime);
            Report(true, "");
            if (Application.isBatchMode) EditorApplication.Exit(0);
        }
        catch (Exception error)
        {
            Debug.LogException(error);
            Report(false, error.ToString());
            if (Application.isBatchMode) EditorApplication.Exit(1);
            else throw;
        }
    }
    static void VerifyGame(StudioRuntime runtime)
    {
        var game = runtime.gameObject.AddComponent<StudioGame>(); game.Initialize(runtime);
        game.Step(1, 0, false, false, 1);
        Require(game.State.X == 2, "Game movement uses Step");
        game.Step(0, 0, true, false, 0);
        game.Step(0, 0, false, false, 0.8f);
        Require(!game.State.Collected[0] && !game.State.Collected[1] && !game.State.Collected[2], "Distant attack misses");
        game.Step(0, 0, false, true, 0);
        game.Step(-1, 0, false, false, 0.5f);
        game.Step(0, 1, false, false, 0.25f);
        game.Step(0, 0, true, false, 0);
        Require(!game.State.Collected[0], "Attack input does not collect immediately");
        game.Step(0, 0, false, false, 0.319f);
        Require(!game.State.Collected[0], "No game hit before authored 320ms contact");
        game.Step(0, 0, false, false, 0.001f);
        Require(game.State.Collected[0], "Game hit at authored contact");
        Require(!runtime.transform.Find("Crystal 1").gameObject.activeSelf, "Hit hides native target");
        game.Step(0, 0, false, false, 0.481f);
        game.Step(1, 0, false, false, 0.5f); game.Step(0, 1, false, false, 0.5f);
        game.Step(0, 0, true, false, 0); game.Step(0, 0, false, false, 0.801f);
        Require(game.State.Collected[1] && !game.State.Won, "Second crystal preserves running game");
        game.Step(1, 0, false, false, 0.5f); game.Step(0, -1, false, false, 0.5f);
        game.Step(0, 0, true, false, 0); game.Step(0, 0, false, false, 0.32f);
        Require(game.State.Won && !runtime.transform.Find("Crystal 3").gameObject.activeSelf, "Third contact wins game");
        game.Step(0, 0, false, true, 0);
        Require(!game.State.Won && game.State.X == 0 && game.State.Z == 0 && !game.State.Attacking, "Reset restores game state");
        Require(runtime.transform.Find("Crystal 1").gameObject.activeSelf && runtime.transform.Find("Crystal 2").gameObject.activeSelf && runtime.transform.Find("Crystal 3").gameObject.activeSelf, "Reset restores all native targets");
    }
    static void Report(bool passed, string error)
    {
        var report = new StudioAcceptanceResult { passed = passed, engine = Application.unityVersion, error = error,
            checks = passedChecks.ToArray() };
        File.WriteAllText(Path.Combine(StudioRuntime.Root, "unity-verification.json"), JsonUtility.ToJson(report, true));
    }
    static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
        passedChecks.Add(message);
        Debug.Log("Studio check passed " + message);
    }
}
