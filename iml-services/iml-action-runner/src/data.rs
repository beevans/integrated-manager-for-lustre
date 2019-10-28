// Copyright (c) 2019 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

use crate::error::ActionRunnerError;
use futures::{channel::oneshot, lock::Mutex};
use iml_wire_types::{Action, ActionId, Fqdn, Id, ManagerMessage, PluginName};
use std::{collections::HashMap, sync::Arc, time::Duration};
use tokio_timer::{clock, delay};

pub type Shared<T> = Arc<Mutex<T>>;
pub type Sessions = HashMap<Fqdn, Id>;
pub type Rpcs = HashMap<ActionId, ActionInFlight>;
pub type SessionToRpcs = HashMap<Id, Rpcs>;

type Sender = oneshot::Sender<Result<serde_json::Value, String>>;

pub struct ActionInFlight {
    tx: Sender,
    pub action: Action,
}

impl ActionInFlight {
    pub fn new(action: Action, tx: Sender) -> Self {
        Self { action, tx }
    }
    pub fn complete(
        self,
        x: Result<serde_json::Value, String>,
    ) -> Result<(), Result<serde_json::Value, String>> {
        self.tx.send(x)
    }
}

/// Waits the given duration for a session matching the
/// `Fqdn` to appear. If a session appears a clone of `Id` is
/// returned.
///
/// If a session does not appear within the duration an Error is raised.
pub async fn await_session(
    fqdn: Fqdn,
    sessions: Shared<Sessions>,
    timeout: Duration,
) -> Result<Id, ActionRunnerError> {
    let until = clock::now() + timeout;

    loop {
        if clock::now() >= until {
            tracing::info!(
                "Could not find a session for {} after {:?} seconds",
                fqdn,
                timeout.as_secs()
            );

            return Err(ActionRunnerError::AwaitSession(fqdn.clone()));
        }

        if let Some(id) = sessions.lock().await.get(&fqdn) {
            return Ok(id.clone());
        }

        let when = clock::now() + Duration::from_millis(500);

        delay(when).await;
    }
}

pub fn insert_action_in_flight(
    id: Id,
    action_id: ActionId,
    action: ActionInFlight,
    session_to_rpcs: &mut SessionToRpcs,
) {
    let rpcs = session_to_rpcs.entry(id).or_insert_with(HashMap::new);

    rpcs.insert(action_id, action);
}

pub fn get_action_in_flight<'a>(
    id: &Id,
    action_id: &ActionId,
    session_to_rpcs: &'a SessionToRpcs,
) -> Option<&'a ActionInFlight> {
    session_to_rpcs.get(id).and_then(|rpcs| rpcs.get(action_id))
}

pub fn has_action_in_flight(
    id: &Id,
    action_id: &ActionId,
    session_to_rpcs: &SessionToRpcs,
) -> bool {
    session_to_rpcs
        .get(id)
        .and_then(|rpcs| rpcs.get(action_id))
        .is_some()
}

pub fn remove_action_in_flight<'a>(
    id: &Id,
    action_id: &ActionId,
    session_to_rpcs: &'a mut SessionToRpcs,
) -> Option<ActionInFlight> {
    session_to_rpcs
        .get_mut(id)
        .and_then(|rpcs| rpcs.remove(action_id))
}

pub fn create_data_message(
    session_id: Id,
    fqdn: Fqdn,
    body: impl Into<serde_json::Value>,
) -> ManagerMessage {
    ManagerMessage::Data {
        session_id,
        fqdn,
        plugin: PluginName("action_runner".to_string()),
        body: body.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::{await_session, get_action_in_flight, insert_action_in_flight, ActionInFlight};
    use crate::error::ActionRunnerError;
    use futures::{channel::oneshot, lock::Mutex};
    use iml_wire_types::{Action, ActionId, Fqdn, Id};
    use std::{collections::HashMap, sync::Arc, time::Duration};
    use tokio_test::{assert_pending, assert_ready_err, clock::MockClock, task};

    #[test]
    fn test_await_session_will_error_after_timeout() {
        let sessions = Arc::new(Mutex::new(HashMap::new()));

        let mut mock = MockClock::new();

        mock.enter(|handle| {
            let mut task = task::spawn(async {
                await_session(Fqdn("host1".to_string()), sessions, Duration::from_secs(25)).await
            });

            assert_pending!(task.poll());

            handle.advance(Duration::from_secs(26));

            assert_ready_err!(task.poll());
        });
    }

    #[tokio::test]
    async fn test_await_session_will_return_id() -> Result<(), ActionRunnerError> {
        let fqdn = Fqdn("host1".to_string());
        let id = Id("eee-weww".to_string());

        let hm = vec![(fqdn, id.clone())].into_iter().collect();
        let sessions = Arc::new(Mutex::new(hm));

        let actual = await_session(
            Fqdn("host1".to_string()),
            Arc::clone(&sessions),
            Duration::from_secs(30),
        )
        .await?;

        assert_eq!(id, actual);

        assert!(sessions.try_lock().is_some());

        Ok(())
    }

    #[test]
    fn test_insert_action_in_flight() {
        let id = Id("eee-weww".to_string());
        let action = Action::ActionCancel {
            id: ActionId("1234".to_string()),
        };
        let mut session_to_rpcs = HashMap::new();

        let (tx, _) = oneshot::channel();

        let action_id = action.get_id().clone();

        let action_in_flight = ActionInFlight::new(action, tx);

        insert_action_in_flight(id, action_id, action_in_flight, &mut session_to_rpcs);

        assert_eq!(session_to_rpcs.len(), 1);
    }

    #[test]
    fn test_get_action_in_flight() {
        let id = Id("eee-weww".to_string());
        let action = Action::ActionCancel {
            id: ActionId("1234".to_string()),
        };

        let (tx, _) = oneshot::channel();

        let action_id = action.get_id().clone();

        let action_in_flight = ActionInFlight::new(action.clone(), tx);

        let rpcs = vec![(action_id.clone(), action_in_flight)]
            .into_iter()
            .collect();

        let session_to_rpcs = vec![(id.clone(), rpcs)].into_iter().collect();

        let actual = get_action_in_flight(&id, &action_id, &session_to_rpcs).unwrap();

        assert_eq!(actual.action, action);
    }
}
