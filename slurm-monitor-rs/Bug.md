# Bug: Infinite Scroll in STDOUT/STDERR Panels

## Description

When scrolling through STDOUT or STDERR output using arrow keys (Up/Down), PageUp/PageDown, the scroll behavior does not stop at file boundaries. Users can continue to "scroll" even when they have reached the top or bottom of the content.

## Expected Behavior

- When at the **top** of the content (scroll position = 0), pressing Up arrow or PageUp should have no effect
- When at the **bottom** of the content (scroll position = max_scroll), pressing Down arrow or PageDown should have no effect
- Scroll mode indicator `[SCROLL MODE - Press 'q' to exit]` should only appear when actual scrolling occurs

## Actual Behavior

- Pressing arrow keys at boundaries still appears to accept the input and process scrolling
- The "infinite loop" feeling persists - users can keep pressing scroll keys indefinitely without the UI indicating they've reached a boundary

## Relevant Code

### Scroll Functions (`src/ui/app.rs`)

```rust
// scroll_up() - lines 237-268
// scroll_down() - lines 270-306
```

### Key Handling (`src/cli.rs`)

```rust
KeyCode::Up => app.scroll_up(1);
KeyCode::Down => app.scroll_down(1);
KeyCode::PageUp => app.scroll_up(10);
KeyCode::PageDown => app.scroll_down(10);
```

### Rendering (`src/ui/render.rs`)

```rust
// get_visible_lines() - lines 312-323
// Calculates which lines to display based on scroll_pos and max_height
```

## Attempted Fixes (Not Working)

1. **Only enable scroll_mode when position changes:**
   ```rust
   let old_scroll = job.stdout_scroll;
   job.stdout_scroll = job.stdout_scroll.saturating_sub(lines);
   if job.stdout_scroll != old_scroll {
       job.stdout_scroll_mode = true;
   }
   ```

2. **Early return when content is too short to scroll:**
   ```rust
   let max_scroll = job.stdout_lines.len().saturating_sub(self.max_visible_lines);
   if max_scroll == 0 {
       return;
   }
   ```

3. **Exit scroll_mode when at bottom and pressing down:**
   ```rust
   } else if job.stdout_scroll == max_scroll {
       job.stdout_scroll_mode = false;
   }
   ```

## Investigation Needed

1. **Verify scroll position values:** Add debug logging to confirm scroll position calculations are correct at boundaries

2. **Check max_visible_lines accuracy:** The `self.max_visible_lines` in App state may not match the actual rendered `inner_height` in render.rs

3. **Examine event loop:** Check if key events are being processed multiple times or if there's rapid re-rendering causing the "loop" feeling

4. **Test with known content:** Create a test case with fixed content length to isolate the issue

## Reproduction Steps

1. Run `slurm-monitor watch` with an active SLURM job
2. Wait for STDOUT content to appear
3. Press Up arrow repeatedly until reaching the top of the content
4. Continue pressing Up arrow - observe if the UI still responds as if scrolling
5. Repeat test with Down arrow at the bottom of content

## Environment

- Application: slurm-monitor-rs v0.1.0
- Framework: ratatui (TUI rendering)
- Event handling: crossterm
