import argparse
import pathlib

import cv2
import gymnasium as gym
import numpy as np

# import humanoid_bench
from robust_gymnasium.envs.robust_humanoid.env import ROBOTS, TASKS

from robust_gymnasium.configs.robust_setting import get_config
robust_args = get_config().parse_args()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="HumanoidBench environment test")
    parser.add_argument("--env", default="h1-walk-v0", help="e.g. h1-walk-v0")
    # h1-push-v0, h1-reach-v0, h1-slide-v0, h1-pole-v0, h1-truck-v0, h1-stand-v0, h1-run-v0, h1-balance_simple-v0, h1-stair-v0

    # h1-walk-v0, h1-hurdle-v0, h1-crawl-v0, h1-maze-v0, h1-highbar_simple-v0, h1-door-v0, h1-basketball-v0
    # h1-package-v0, h1-sit_simple-v0
    parser.add_argument("--keyframe", default=None)
    parser.add_argument("--policy_path", default=None)
    parser.add_argument("--mean_path", default=None)
    parser.add_argument("--var_path", default=None)
    parser.add_argument("--policy_type", default=None)
    parser.add_argument("--small_obs", default="False")
    parser.add_argument("--obs_wrapper", default="False")
    parser.add_argument("--sensors", default="")
    parser.add_argument("--render_mode", default="rgb_array")  # "human" or "rgb_array".
    # NOTE: to get (nicer) 'human' rendering to work, you need to fix the compatibility issue between mujoco>3.0 and gymnasium: https://github.com/Farama-Foundation/Gymnasium/issues/749
    args = parser.parse_args()

    kwargs = vars(args).copy()
    kwargs.pop("env")
    kwargs.pop("render_mode")
    if kwargs["keyframe"] is None:
        kwargs.pop("keyframe")
    print(f"arguments: {kwargs}")

    # Test offscreen rendering
    print(f"Test offscreen mode...")
    env = gym.make(args.env, render_mode="rgb_array", **kwargs)
    ob, _ = env.reset()
    if isinstance(ob, dict):
        print(f"ob_space = {env.observation_space}")
        print(f"ob = ")
        for k, v in ob.items():
            print(f"  {k}: {v.shape}")
    else:
        print(f"ob_space = {env.observation_space}, ob = {ob.shape}")
    print(f"ac_space = {env.action_space.shape}")

    img = env.render()
    # env.render(420, 380, 0)
    # data = np.asarray(img.read_pixels(420, 380, depth=False)[::-1, :, :], dtype=np.uint8)
    # if data is not None:
    #     cv2.imwrite("test{0}.png".format(i), data)
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    cv2.imwrite("test_env_img.png", rgb_img)

    # Test online rendering with interactive viewer
    print(f"Test onscreen mode...")
    env = gym.make(args.env, render_mode=args.render_mode, **kwargs)
    ob, _ = env.reset()
    if isinstance(ob, dict):
        print(f"ob_space = {env.observation_space}")
        print(f"ob = ")
        for k, v in ob.items():
            print(f"  {k}: {v.shape}")
            assert (
                v.shape == env.observation_space.spaces[k].shape
            ), f"{v.shape} != {env.observation_space.spaces[k].shape}"
        assert ob.keys() == env.observation_space.spaces.keys()
    else:
        print(f"ob_space = {env.observation_space}, ob = {ob.shape}")
        assert env.observation_space.shape == ob.shape
    print(f"ac_space = {env.action_space.shape}")
    # print("observation:", ob)
    env.render()
    ret = 0
    while True:
        action = env.action_space.sample()
        robust_input = {
            "action": action,
            "robust_type": "action",
            "robust_config": robust_args,
        }
        ob, rew, terminated, truncated, info = env.step(robust_input)
        img = env.render()
        ret += rew

        if args.render_mode == "rgb_array":
            cv2.imshow("test_env", img[:, :, ::-1])
            cv2.waitKey(1)

        if terminated or truncated:
            ret = 0
            env.reset()
    env.close()
