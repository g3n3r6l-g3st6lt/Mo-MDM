# Audiovisual Journal – October 7, 2025

### Video: https://www.youtube.com/watch?v=S21RdSBYkvM

Another audiovisual journal. The date today is October 7th, 2025. It’s 11:38 a.m., and it is a Tuesday.

Because I did not document the process of using pixel art to create my character, what I will do now is go through the same process creating a new character. This is to show the steps I take, and also to understand how the generative AI aspect of Pixel Lab makes the workflow of creating pixel art assets for game characters quite simple.

I started with this method because it saves me a lot of time and compensates for my skill shortcomings — mainly character concept art and pixel art, which would take significantly more time to learn than to create this way. You can check the documentation to understand how it works and the ethical dimensions of it. Importantly, it does not infringe upon the copyright of any artist and does not unethically source its learning data.

You create an account (or not), sign in, and then simply go to the character section, which opens your character. This is my character that I created, which resembles me.

## Character Prompting

Now I’ll type a description or prompt for the character. What I find works well is to describe it from high level to low level:

Skin complexion

Eye color

Hair color

Body structure (heavyset, muscular, slim)

Then accessories, clothing, etc.

For example:

Create a character of a detective.

Brown complexion.

Blue eyes.

Male, slim.

Wearing a beige trench coat.

Dark brown Oxford shoes.

This level of detail is too specific for pixel art (it won’t show everything), but giving details helps the model learn the general characteristics and how best to represent them in pixel form.

Once you write the prompt, you generate it. That takes you to another page where you can set canvas size for your sprite (small, medium, large). For my original character I chose large, so I’ll stick with that now.

You then choose camera orientation for your game or animation — side scroller, top-down, or oblique (beta). My game is high top-down, so I’ll go with that.

## Character Settings

Next are character proportions. You can adjust manually or pick presets like “realistic,” “heroic,” or “cartoon.” Let’s choose heroic for now.

Then there are advanced options:

Sprite sheet: one-directional or four-directional (I’ll do four this time).

AI freedom: how loosely or strictly it interprets your prompt.

Outline style: single color, black outline, selective outline. (I’ll pick single color, black outline — classic.)

Shading: basic, medium, detailed, highly detailed. (I’ll choose medium shading with high detail level.)

Padding: spacing around the character, useful for cropping and applying mechanics in your engine.

In my case, I’m using Unreal Engine. I’ll record another video showing how to apply the sprites in Unreal using Paper2D/PaperZ plugin.

## Generating the Character

Now let’s generate the character. It takes some time since this is framed animation. It works like other generative AI tools but maintains consistency across frames so that proportions, colors, and shapes match.

As it renders, you can already see it looks pretty accurate: eyes, trench coat, fedora, shoes. I didn’t specify clothing under the coat, so the model is improvising. Since I used “detective” in the prompt, it inferred a certain aesthetic.

This looks pretty good. The reason I’m using Pixel Lab is to test if it speeds up development and allows more iterations. For character animation iterations, it definitely does.

Here is my detective — very nice character.

## Animation

Now, let’s see how we can animate it. Pixel Lab offers many animation options, but you cannot make bespoke animations, which is a limitation. For custom or unique animations, Pixel Lab won’t always be the right answer. But it’s great for general looks and templates, which you can then refine in Photoshop or Procreate.

Pixel Lab has built-in animations like idle, jump, run, walk, and even backflip (in beta). Beta means the model is still learning, so results may be inconsistent, requiring multiple iterations. Non-beta animations usually refine faster.

Let’s pick a simple 8-frame walk. You can also adjust advanced options, but I don’t recommend changing them from your character’s original settings. Then choose which directions you want (e.g., four directions) and generate. You can generate live (see frames as they’re created) or in the background.

Note: without a subscription, you’re limited by the number of generations, animations, and refinements per month. The free version works fine for sketches and brainstorming, but for full characters with animations, the subscription is worth it.

Waiting and Refining

Now we wait. It usually takes 2–10 minutes depending on animation complexity. While waiting, I can show some of the animations I already made:

Walking (fairly consistent).

Jumping (some artifact issues, like color changes mid-frame).

Running (needed multiple iterations but now consistent).

You can download animations as GIFs and then separate them into frames for use in Unreal as sprites. Pixel Lab also has Pixelorama, a subsidiary tool that lets you control frames, recolor, reposition, etc.

## Wrap-Up

The animation is now complete. Shading looks nice, and you can repeat this for other movements.

This has been a documentation of using Pixel Lab to create a pixel art character and animate it for a simple walk cycle.

Thank you — that’s the end of the journal.
