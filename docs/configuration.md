# Configuration

Homer works without a configuration file. Its defaults are:

```yaml
model: qwen2.5:7b
ollama_host: http://localhost:11434
timeout_seconds: 60
context_tokens: 8192
```

Configuration is selected in this order:

1. `--config PATH`
2. `HOMER_CONFIG`
3. `~/.config/homer/config.yaml`
4. Built-in defaults

Copy `config.example.yaml` to the user configuration location if you want persistent changes.
Relative `style_guide` paths are resolved from the configuration file's directory.

```zsh
mkdir -p ~/.config/homer
cp config.example.yaml ~/.config/homer/config.yaml
homer config show
```

The model and host can also be changed for one invocation:

```zsh
homer --model qwen2.5:3b "list JPEG files"
homer --ollama-host http://127.0.0.1:11434 doctor
```

Homer warns when the configured host is not a loopback address because prompts and writing input
will leave the Mac. Unknown settings are rejected instead of silently ignored.
