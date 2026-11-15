import unittest
from unittest.mock import patch
import numpy as np
from quant import models, pipeline, planning, targets
from quant.contracts import PreparedDataset, FittedModel
from quant.model_adapters import ModelAdapter, register, _ADAPTERS


class ResearchContractsTest(unittest.TestCase):
    def partitions(self, sequence=False, binary=False):
        rng = np.random.default_rng(42)
        result = {}
        for name in ('train', 'valid', 'test'):
            x = rng.normal(size=(32, 3, 2) if sequence else (32, 2))
            y = (x.reshape(32, -1)[:, 0] > 0).astype(float) if binary else x.reshape(32, -1)[:, 0]
            result[name] = PreparedDataset(tuple(f'{name}:{i}' for i in range(32)), x, y)
        return result

    def test_backends(self):
        for model in models.registry():
            if not model['available']:
                with self.subTest(model=model['id']):
                    self.skipTest('模型依赖不可用：' + model['id'])
                continue
            for task in ('regression', 'binary'):
                with self.subTest(model=model['id'], task=task):
                    parts = self.partitions(model['input'] == 'sequence', task == 'binary')
                    config = {'model': model['id'], 'epochs': 1, 'model_params': {}}
                    fitted, predictions = pipeline.train_and_predict(config, task, parts, lambda _: None)
                    self.assertEqual(predictions['test'].sample_ids, parts['test'].sample_ids)
                    np.testing.assert_allclose(predictions['test'].values, fitted.predict(parts['test'].values))
                    self.assertEqual(predictions['test'].semantic, 'probability' if task == 'binary' else 'value')

    def test_overlap_rejected_before_training(self):
        parts = self.partitions()
        parts['test'] = parts['train']
        with patch.object(models, 'fit') as fit:
            with self.assertRaises(ValueError):
                pipeline.train_and_predict({'model': 'lightgbm', 'epochs': 1}, 'regression', parts, print)
            fit.assert_not_called()

    def test_plan_rejects_event_sequence(self):
        with patch.object(models, 'registry', return_value=[{'id': 'lstm', 'available': True, 'tasks': ['binary'], 'input': 'sequence'}]):
            with self.assertRaises(ValueError):
                planning.compile_plan({'model': 'lstm', 'sample_mode': 'chan_event'}, targets.STRUCTURE_CONFIRMATION)

    def test_custom_model_runs_without_core_changes(self):
        def trainer(kind, task, xtrain, ytrain, xvalid, yvalid, epochs, progress, seed, params):
            mean = float(ytrain.mean())
            return FittedModel({'mean': mean}, [], {}, lambda x: np.full(len(x), mean))
        adapter = ModelAdapter('test_mean', 'vector', ('regression',), '', trainer,
                               lambda task: [], {'name': 'Mean', 'group': 'test'})
        with patch.dict(_ADAPTERS):
            register(adapter)
            config = {'model': 'test_mean', 'epochs': 1, 'sample_mode': 'bar'}
            plan = planning.compile_plan(config, targets.get('forward_return'))
            self.assertEqual(plan['model'], 'test_mean')
            parts = self.partitions()
            _, output = pipeline.train_and_predict(config, 'regression', parts, lambda _: None)
            np.testing.assert_allclose(output['test'].values, parts['train'].labels.mean())
            with self.assertRaises(ValueError):
                register(adapter)
            with self.assertRaises(ValueError):
                models.fit('test_mean', 'binary', parts['train'].values, parts['train'].labels,
                           parts['valid'].values, parts['valid'].labels, 1, print)

    def test_test_data_not_passed_to_fit(self):
        parts = self.partitions()
        dummy = FittedModel({}, [], {}, lambda x: np.zeros(len(x)))
        with patch.object(models, 'fit', return_value=dummy) as fit:
            pipeline.train_and_predict({'model': 'lightgbm', 'epochs': 1}, 'regression', parts, lambda _: None)
            self.assertFalse(any(arg is parts['test'].values or arg is parts['test'].labels for arg in fit.call_args.args))


if __name__ == '__main__':
    unittest.main()
