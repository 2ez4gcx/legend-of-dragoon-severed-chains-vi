package legend.core.platform.input;

import legend.game.modding.coremod.CoreMod;
import legend.game.modding.events.input.RegisterDefaultInputBindingsEvent;
import legend.game.saves.ConfigCollection;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.legendofdragoon.modloader.registries.RegistryDelegate;
import org.legendofdragoon.modloader.registries.RegistryId;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

import static legend.core.GameEngine.EVENTS;
import static legend.core.GameEngine.PLATFORM;
import static legend.core.GameEngine.REGISTRIES;

public final class InputBindings {
  private InputBindings() { }

  private static final Logger LOGGER = LogManager.getFormatterLogger(InputBindings.class);

  private static final Map<Class<? extends InputActivation>, List/*<InputBinding<?>>*/> BINDINGS = new HashMap<>();

  public static void initBindings() {
    PLATFORM.resetActionStates();
    BINDINGS.clear();
    EVENTS.postEvent(new RegisterDefaultInputBindingsEvent(BINDINGS));
  }

  public static void loadBindings(final ConfigCollection config) {
    final Map<RegistryDelegate<InputAction>, List<InputActivation>> savedBindings = config.getConfig(CoreMod.CONTROLLER_KEYBINDS_CONFIG.get());

    // [sc-android] gamepad buttons of every action before the saved bindings replace them (callers run initBindings first,
    // so these are the defaults)
    final Map<InputAction, List<InputActivation>> gamepadDefaults = new HashMap<>();
    for(final RegistryId actionId : REGISTRIES.inputActions) {
      final InputAction action = REGISTRIES.inputActions.getEntry(actionId).get();
      final List<InputActivation> gamepad = gamepadActivations(getActivationsForAction(action));

      if(!gamepad.isEmpty()) {
        gamepadDefaults.put(action, gamepad);
      }
    }

    savedBindings.forEach(InputBindings::overwriteBindings);

    // [sc-android] the touch pad is a virtual gamepad, so an action left without any gamepad button can't be used on the
    // phone at all. That happens with saves brought over from a PC: rebinding an action there clears all of its old
    // activations, so a keyboard player who moved "open menu" to a key also lost the controller button, and on the phone
    // the menu (the only way to Options -> Controls to fix it) never opens. Give such actions their default gamepad
    // buttons back, keeping the keyboard keys.
    for(final Map.Entry<InputAction, List<InputActivation>> e : gamepadDefaults.entrySet()) {
      final List<InputActivation> activations = getActivationsForAction(e.getKey());

      if(gamepadActivations(activations).isEmpty()) {
        activations.addAll(e.getValue());
        overwriteBindings(e.getKey(), activations);
        LOGGER.info("[sc-android] %s had no gamepad binding, restored the default one", e.getKey().getRegistryId());
      }
    }
  }

  /** [sc-android] the activations a gamepad (or the touch pad) can trigger */
  private static List<InputActivation> gamepadActivations(final List<InputActivation> activations) {
    final List<InputActivation> out = new ArrayList<>();

    for(final InputActivation activation : activations) {
      if(activation instanceof ButtonInputActivation || activation instanceof AxisInputActivation) {
        out.add(activation);
      }
    }

    return out;
  }

  public static void saveBindings(final ConfigCollection config) {
    final Map<RegistryDelegate<InputAction>, List<InputActivation>> activations = new HashMap<>();

    for(final RegistryId actionId : REGISTRIES.inputActions) {
      final RegistryDelegate<InputAction> action = REGISTRIES.inputActions.getEntry(actionId);
      activations.put(action, getActivationsForAction(action.get()));
    }

    config.setConfig(CoreMod.CONTROLLER_KEYBINDS_CONFIG.get(), activations);
  }

  public static <T extends InputActivation> List<InputBinding<T>> getBindings(final Class<T> cls) {
    final List list = BINDINGS.get(cls);

    if(list == null) {
      return List.of();
    }

    return list;
  }

  public static List<InputActivation> getActivationsForAction(final InputAction action) {
    final List<InputActivation> activations = new ArrayList<>();

    for(final List<InputBinding<?>> bindings : BINDINGS.values()) {
      for(final InputBinding<?> binding : bindings) {
        if(binding.action == action) {
          activations.add(binding.activation);
        }
      }
    }

    return activations;
  }

  public static void overwriteBindings(final RegistryDelegate<InputAction> action, final List<InputActivation> activations) {
    if(!action.isValid()) {
      LOGGER.info("Skipping unknown InputAction %s", action);
      return;
    }

    overwriteBindings(action.get(), activations);
  }

  public static void overwriteBindings(final InputAction action, final List<InputActivation> activations) {
    // Clear all existing bindings for the action
    for(final var entry : BINDINGS.entrySet()) {
      final Iterator it = entry.getValue().iterator();

      while(it.hasNext()) {
        final InputBinding binding = (InputBinding)it.next();

        if(binding.action == action) {
          it.remove();
        }
      }
    }

    // Add the new bindings
    for(final InputActivation activation : activations) {
      BINDINGS.computeIfAbsent(activation.getClass(), key -> new ArrayList<>()).add(new InputBinding(action, activation));
    }
  }
}
